#!/usr/bin/env python3
"""日本酒造組合中央会「酒蔵検索」(https://japansake.or.jp/sakagura/jp/)から
全国の清酒蔵元・焼酎蔵元(蔵名・住所・都道府県・カテゴリ)を取得し、
master_list_raw.jsonに保存する。カテゴリ("sake"/"shochu")はサイト側の
分類(class="sake"/"shochu")をそのまま使う。

OpenStreetMapに登録が無い蔵が多く、fetch_breweries.pyだけでは清酒蔵元
(全国で少なくとも1,200件ほど)の半分にも満たないデータしか取れないことが
分かったため、業界団体の公式リストを一次情報源として使う。

robots.txtにクロール制限は無く、ページ上に明確な再利用禁止の記載も無いことを
事前に確認している。ただし解説文などの著作物はそのまま複製せず、蔵名・住所・
商品名といった事実情報のみを抽出する方針にする。

標準ライブラリのみで書かれているので、pip installは不要。
使い方: python3 scripts/scrape_master_list.py
"""

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_PATH = BASE_DIR / "master_list_raw.json"
WEBSITE_CACHE_PATH = BASE_DIR / "master_list_website_cache.json"

HEADERS = {"User-Agent": "sake-brewery-map/1.0 (personal PWA project; github.com/kimuhixy-ux/sake-brewery-map)"}
REQUEST_DELAY_SECONDS = 1.0
DETAIL_REQUEST_DELAY_SECONDS = 0.25
DETAIL_MAX_WORKERS = 6
MAX_RETRIES = 3

# https://japansake.or.jp/sakagura/jp/ トップページのナビゲーションから抽出した
# 47都道府県のURLスラッグ。
PREF_SLUGS = {
    "hokkaido": "北海道", "aomori": "青森県", "iwate": "岩手県", "miyagi": "宮城県",
    "akita": "秋田県", "yamagata": "山形県", "fukushima": "福島県",
    "ibaraki": "茨城県", "tochigi": "栃木県", "gunma": "群馬県", "saitama": "埼玉県",
    "chiba": "千葉県", "tokyo": "東京都", "kanagawa": "神奈川県",
    "niigata": "新潟県", "toyama": "富山県", "ishikawa": "石川県", "fukui": "福井県",
    "yamanashi": "山梨県", "nagano": "長野県", "gifu": "岐阜県", "shizuoka": "静岡県",
    "aichi": "愛知県",
    "mie": "三重県", "shiga": "滋賀県", "kyoto": "京都府", "osaka": "大阪府",
    "hyogo": "兵庫県", "nara": "奈良県", "wakayama": "和歌山県",
    "tottori": "鳥取県", "shimane": "島根県", "okayama": "岡山県", "hiroshima": "広島県",
    "yamaguchi": "山口県",
    "tokushima": "徳島県", "kagawa": "香川県", "ehime": "愛媛県", "kochi": "高知県",
    "fukuoka": "福岡県", "saga": "佐賀県", "nagasaki": "長崎県", "kumamoto": "熊本県",
    "oita": "大分県", "miyazaki": "宮崎県", "kagoshima": "鹿児島県", "okinawa": "沖縄県",
}

# 蔵名・住所・カテゴリ(清酒/焼酎)・代表銘柄を抽出する正規表現。
# サイトのHTML構造(2026年7月時点)に基づく:
# <li> <a href="URL"><div class="img" .../><div class="category1"> <span class="sake"></span>
# </div><h3>蔵名</h3><div class="addr">住所</div><div class="sake-shochu">...</div>...</a></li>
ENTRY_PATTERN = re.compile(
    r'<a href="(?P<url>https://japansake\.or\.jp/sakagura/jp/[a-z-]+/[a-z0-9-]+/)">'
    r'.*?<span class="(?P<category>sake|shochu)"></span>'
    r'.*?<h3>(?P<name>.*?)</h3>'
    r'<div class="addr">(?P<addr>.*?)</div>',
    re.DOTALL,
)

# 個別の酒蔵ページにある「HP」行だけを対象にする。ページ下部にある
# 日本酒造組合中央会自身のURLを誤って酒蔵の公式サイトとして拾わない。
WEBSITE_PATTERN = re.compile(
    r"<th>\s*HP\s*</th>\s*<td[^>]*>\s*<a[^>]+href=[\"'](?P<url>[^\"']+)[\"']",
    re.IGNORECASE | re.DOTALL,
)


def fetch_url(url):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            print(f"  失敗({attempt}回目): {e}")
        except OSError as e:
            print(f"  失敗({attempt}回目): {e}")
        time.sleep(3)
    raise RuntimeError(f"取得に失敗しました: {url}")


def strip_tags(html):
    return re.sub(r"<[^>]+>", "", html).strip()


def normalize_website_url(raw_url):
    """サイト側で省略されることがあるschemeを補い、HTTP(S)だけを返す。"""
    url = raw_url.strip()
    if re.match(r"^[a-z][a-z0-9+.-]*:", url, re.IGNORECASE) and not re.match(
        r"^https?://", url, re.IGNORECASE
    ):
        return None
    if url.startswith("//"):
        url = "https:" + url
    elif not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url.lstrip("/")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return url


def parse_website(html):
    match = WEBSITE_PATTERN.search(html)
    return normalize_website_url(match.group("url")) if match else None


def enrich_websites(entries):
    cache = {}
    if WEBSITE_CACHE_PATH.exists():
        with open(WEBSITE_CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)
        print(f"公式サイトURLキャッシュを読み込みました({len(cache)}件)。")

    missing_urls = [e["source_url"] for e in entries if e["source_url"] not in cache]

    def fetch_website(source_url):
        html = fetch_url(source_url)
        time.sleep(DETAIL_REQUEST_DELAY_SECONDS)
        return parse_website(html) if html else None

    if missing_urls:
        completed = 0
        with ThreadPoolExecutor(max_workers=DETAIL_MAX_WORKERS) as executor:
            futures = {executor.submit(fetch_website, url): url for url in missing_urls}
            for future in as_completed(futures):
                source_url = futures[future]
                cache[source_url] = future.result()
                completed += 1
                if completed % 20 == 0:
                    with open(WEBSITE_CACHE_PATH, "w", encoding="utf-8") as f:
                        json.dump(cache, f, ensure_ascii=False, indent=2)
                if completed % 50 == 0 or completed == len(missing_urls):
                    print(f"  公式サイト [{completed}/{len(missing_urls)}] 新規取得")

    for entry in entries:
        entry["website"] = cache[entry["source_url"]]

    with open(WEBSITE_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    return entries


def parse_entries(html, pref_name):
    entries = []
    for m in ENTRY_PATTERN.finditer(html):
        name = strip_tags(m.group("name")).strip()
        addr = strip_tags(m.group("addr")).strip()
        if not name or not addr:
            continue
        entries.append({
            "name": name,
            "pref": pref_name,
            "address": addr,
            "category": m.group("category"),
            "source_url": m.group("url"),
        })
    return entries


def has_next_page(html):
    return bool(re.search(r'class="next[^"]*"', html)) or bool(re.search(r'>次へ<', html))


def scrape_prefecture(slug, pref_name):
    entries = []
    page = 1
    while True:
        url = (
            f"https://japansake.or.jp/sakagura/jp/{slug}/"
            if page == 1
            else f"https://japansake.or.jp/sakagura/jp/{slug}/page/{page}/"
        )
        html = fetch_url(url)
        if html is None:
            break
        page_entries = parse_entries(html, pref_name)
        if not page_entries and page > 1:
            break
        entries.extend(page_entries)
        if not has_next_page(html):
            break
        page += 1
        time.sleep(REQUEST_DELAY_SECONDS)
    return entries


def main():
    details_only = "--details-only" in sys.argv
    if details_only:
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            all_entries = json.load(f)
    else:
        all_entries = []
        for i, (slug, pref_name) in enumerate(PREF_SLUGS.items(), 1):
            print(f"[{i}/{len(PREF_SLUGS)}] {pref_name} ({slug}) を取得中...")
            entries = scrape_prefecture(slug, pref_name)
            sake_count = sum(1 for e in entries if e["category"] == "sake")
            shochu_count = sum(1 for e in entries if e["category"] == "shochu")
            print(f"  -> 清酒 {sake_count}件 / 焼酎 {shochu_count}件")
            all_entries.extend(entries)
            time.sleep(REQUEST_DELAY_SECONDS)

    enrich_websites(all_entries)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_entries, f, ensure_ascii=False, indent=2)

    sake_total = sum(1 for e in all_entries if e["category"] == "sake")
    shochu_total = sum(1 for e in all_entries if e["category"] == "shochu")
    website_total = sum(1 for e in all_entries if e.get("website"))
    print()
    print(f"合計: {len(all_entries)}件 (清酒{sake_total}件 / 焼酎{shochu_total}件 / 公式サイト{website_total}件)")
    print(f"出力先: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
