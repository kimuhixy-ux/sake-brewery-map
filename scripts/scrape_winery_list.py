#!/usr/bin/env python3
"""日本ワイナリー協会(https://www.winery.or.jp/)の「日本のワイナリー紹介」
ページから、全国のワイナリー(名称・住所)を取得し、winery_list_raw.jsonに
保存する。

国税庁自身は個別ワイナリーの名称・住所を一覧できる構造化データを公開して
いない(「酒蔵マップ」は都道府県別の画像地図で、個別ワイナリー名はテキスト
として取得できない。「酒類等製造免許の新規取得者名等一覧」は2014年以降の
新規免許取得者のみが対象で、老舗ワイナリーが抜け落ちる)。そのため、清酒側の
日本酒造組合中央会と同じ位置づけの業界団体として、日本ワイナリー協会が
紹介する全国のワイナリー一覧を一次情報源として使う。

OSM(craft=wineryタグ)だけでは全国で80件に満たない程度しか拾えず、
業界推定(400件以上)に遠く及ばないことが分かったため、これを補完する。

サイトはエリア別(北海道/北海道(余市)/東北/新潟/関東/山梨(勝沼)/
山梨(東部)/山梨(西部)/長野/長野(塩尻)/中部・北陸/近畿/中国・四国/九州の
14エリア)にワイナリー一覧ページがあり、各ページから個別ワイナリーの
詳細ページURLを収集したうえで、詳細ページごとに名称・所在地・ホームページを
取得する。長野と長野(塩尻)のように地域区分が重複することがあるため、
ワイナリーIDで全体を重複排除する。

robots.txtにクロール制限は無いことを確認している。解説文などの著作物は
複製せず、名称・住所・ホームページURLといった事実情報のみを抽出する。

標準ライブラリのみで書かれているので、pip installは不要。
使い方: python3 scripts/scrape_winery_list.py
"""

import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_PATH = BASE_DIR / "winery_list_raw.json"

HEADERS = {"User-Agent": "sake-brewery-map/1.0 (personal PWA project; github.com/kimuhixy-ux/sake-brewery-map)"}
REQUEST_DELAY_SECONDS = 1.0
MAX_RETRIES = 3

AREA_SLUGS = [
    "hokkaido", "yoichi", "tohoku", "niigata", "kanto",
    "yamanashi-katsunuma", "yamanashi-east", "yamanashi-west",
    "nagano", "shiojiri", "chubu", "kinki", "chugoku", "kyushu",
]

FULL_PREF_NAMES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県", "静岡県",
    "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
    "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県",
    "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]

# 複数の都道府県にまたがらないエリアのみ、都道府県が住所から判別できない
# 場合のフォールバックとして使う(東北・関東・中部・北陸・近畿・中国・四国・
# 九州は複数県にまたがるため対象外)。
AREA_TO_PREF = {
    "hokkaido": "北海道", "yoichi": "北海道",
    "niigata": "新潟県",
    "yamanashi-katsunuma": "山梨県", "yamanashi-east": "山梨県", "yamanashi-west": "山梨県",
    "nagano": "長野県", "shiojiri": "長野県",
}

# 都道府県の正式名称の末尾1文字(都道府県)を省略した表記(例:「福島会津若松市」の
# 「福島」)がまれに住所にそのまま入力されていることがあるため、これも拾う。
SHORT_PREF_MAP = {name[:-1]: name for name in FULL_PREF_NAMES if name != "北海道"}

# 政令指定都市など、住所に都道府県名を伴わず市名だけで書かれることがある
# 主要都市のフォールバック。
CITY_TO_PREF = {
    "さいたま市": "埼玉県", "千葉市": "千葉県", "横浜市": "神奈川県", "川崎市": "神奈川県",
    "相模原市": "神奈川県", "新潟市": "新潟県", "静岡市": "静岡県", "浜松市": "静岡県",
    "名古屋市": "愛知県", "京都市": "京都府", "大阪市": "大阪府", "堺市": "大阪府",
    "神戸市": "兵庫県", "岡山市": "岡山県", "広島市": "広島県", "北九州市": "福岡県",
    "福岡市": "福岡県", "熊本市": "熊本県", "札幌市": "北海道", "仙台市": "宮城県",
    "東根市": "山形県",
}

WINERY_LINK_RE = re.compile(r'winery-map/(\d+)/')

NAME_RE = re.compile(
    r'<h1[^>]*Head__Page[^>]*>\s*<span class="Text">(?P<name>.*?)'
    r'(?:<span class="Badge">|</span>\s*</h1>)',
    re.DOTALL,
)
ADDRESS_RE = re.compile(r'<th>所在地</th>\s*<td>(?P<addr>.*?)</td>', re.DOTALL)
WEBSITE_RE = re.compile(r'<th>ホームページ</th>\s*<td><a href="(?P<url>[^"]*)"', re.DOTALL)


def fetch_url(url):
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last_error = e
            print(f"  失敗({attempt}回目): {e}")
        except OSError as e:
            last_error = e
            print(f"  失敗({attempt}回目): {e}")
        time.sleep(3)
    raise RuntimeError(f"取得に失敗しました: {url} ({last_error})")


def strip_tags(html):
    return re.sub(r"<[^>]+>", "", html).strip()


def collect_winery_ids():
    """14エリアの一覧ページから、個別ワイナリーの投稿IDを重複無しで集める。
    住所から都道府県が判別できない場合のフォールバック用に、最初に見つかった
    エリアのスラッグも記録しておく。
    """
    ids = []
    id_to_area = {}
    seen = set()
    for i, slug in enumerate(AREA_SLUGS, 1):
        url = f"https://www.winery.or.jp/winery-map/area/{slug}/"
        print(f"[{i}/{len(AREA_SLUGS)}] {slug} の一覧を取得中...")
        html = fetch_url(url)
        found = sorted(set(WINERY_LINK_RE.findall(html or "")), key=int)
        new_count = 0
        for wid in found:
            if wid not in seen:
                seen.add(wid)
                ids.append(wid)
                id_to_area[wid] = slug
                new_count += 1
        print(f"  -> {len(found)}件(新規{new_count}件)")
        time.sleep(REQUEST_DELAY_SECONDS)
    return ids, id_to_area


def guess_pref(address, area_slug=None):
    cleaned = re.sub(r"^〒\d{3}-?\d{4}\s*", "", address).strip()
    for pref in FULL_PREF_NAMES:
        if cleaned.startswith(pref):
            return pref
    for city, pref in CITY_TO_PREF.items():
        if cleaned.startswith(city):
            return pref
    for short, full in SHORT_PREF_MAP.items():
        if cleaned.startswith(short):
            return full
    if area_slug:
        return AREA_TO_PREF.get(area_slug)
    return None


def parse_winery_detail(html, area_slug=None):
    name_m = NAME_RE.search(html)
    addr_m = ADDRESS_RE.search(html)
    if not name_m or not addr_m:
        return None
    name = strip_tags(name_m.group("name"))
    address = strip_tags(addr_m.group("addr"))
    if not name or not address:
        return None
    website_m = WEBSITE_RE.search(html)
    website = website_m.group("url").strip() if website_m else None
    return {
        "name": name,
        "pref": guess_pref(address, area_slug),
        "address": address,
        "website": website,
        "category": "wine",
    }


def main():
    winery_ids, id_to_area = collect_winery_ids()
    print(f"\n合計{len(winery_ids)}件のワイナリーページを取得します。\n")

    records = []
    for i, wid in enumerate(winery_ids, 1):
        url = f"https://www.winery.or.jp/winery-map/{wid}/"
        print(f"[{i}/{len(winery_ids)}] {url} を取得中...")
        try:
            html = fetch_url(url)
        except RuntimeError as e:
            print(f"  スキップします: {e}")
            continue
        if html is None:
            continue
        record = parse_winery_detail(html, id_to_area.get(wid))
        if record:
            records.append(record)
        else:
            print("  -> 名称または住所が見つからずスキップしました。")
        time.sleep(REQUEST_DELAY_SECONDS)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print()
    print(f"合計: {len(records)}件")
    print(f"出力先: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
