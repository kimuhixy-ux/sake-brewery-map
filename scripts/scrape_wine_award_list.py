#!/usr/bin/env python3
"""日本ワインコンクール(jwine-compe.jp、OIV(国際ブドウ・ワイン機構)公認、
山梨県・KOAP等が運営)の受賞結果PDFを取得し、ワイナリーごとの受賞歴を
wine_award_raw.jsonに保存する(全国新酒鑑評会に対するsake_award_raw.jsonと
同じ位置づけ)。

日本ワインコンクールは各年のアーカイブページ(https://jwine-compe.jp/archive/
{年}/)から、部門別(欧州赤・欧州白・国内赤・国内白・甲州・北米赤・北米白・
ブレンド赤・ブレンド白・極甘口・ロゼ・スパークリングの12部門)の受賞結果PDFに
リンクしている。掲載されているワインは全て「受賞ワイン」で、金賞には
「金」「金・部門最高賞」のように「金」の文字が必ず先頭に付く。

PDFファイル名の命名規則は年度によってばらばらで、隣接する年で全く違う
パターンが使われている(例: 2018-2019年は"02.5-2018resule-K.pdf"、2022年は
"02-05-2022result-K.pdf"、2023年は"受賞結果一覧2023K.pdf"、2024-2025年は
"2024年採点結果（05甲州）.pdf")。そのため、命名規則からURLを組み立てることは
せず、毎年のアーカイブページ本体をスクレイピングしてPDFリンクを実際に
発見する方式を取る(審査員名簿PDFやGG賞紹介PDFはリンクのファイル名に
"judge"/"審査員"/"ＧＧ賞"を含むため、これらは対象から除外する)。

PDF内の表は「賞名|銘柄|醸造年|会社名等|醸造地|容器容量|販売価格|
出品時実存本数|販売時期」という列を持つが、列位置・部門列の有無が年度に
よって異なる(2024年以降は部門が見出しに移り列自体が無い)ため、列位置に
頼らず以下のヒューリスティックで抽出する:
  1. 行内から都道府県名(例: 山梨県)を検索し、見つかった最後の出現位置を
     醸造地とする。
  2. 醸造地より手前にある行内最後の単独4桁の年(醸造年列の値。銘柄名に
     ヴィンテージ年が含まれることがあるため、醸造地に一番近いものを使う)
     の直後から醸造地の直前までを会社名(ワイナリー名)とする。
  3. 行頭付近にある「金/銀/銅」+任意の「・◯◯賞」を賞名とし、「金」で
     始まれば金賞として扱う。
このヒューリスティックは2018〜2025年度の複数フォーマットで手動検証済み。

対象年度は2025年(最新)から2016年までの直近10年度分。ただし2020年度・
2021年度はアーカイブページ自体が存在しない(HTTPステータス404。新型コロナ
禍でコンクールが中止・非開催になったとみられる)ため、この2年度は欠落する。

robots.txtにクロール制限は無いことを確認している。

標準ライブラリのみで書かれているが、pdftotextコマンド(poppler-utils)が
別途必要。
使い方: python3 scripts/scrape_wine_award_list.py
"""

import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_PATH = BASE_DIR / "wine_award_raw.json"

HEADERS = {"User-Agent": "sake-brewery-map/1.0 (personal PWA project; github.com/kimuhixy-ux/sake-brewery-map)"}
REQUEST_DELAY_SECONDS = 1.0
MAX_RETRIES = 3

ARCHIVE_URL_TEMPLATE = "https://jwine-compe.jp/archive/{year}/"

# 2020年度・2021年度はアーカイブページが404(コンクール非開催とみられる)。
TARGET_YEARS = [2025, 2024, 2023, 2022, 2019, 2018, 2017, 2016]

# 受賞結果PDF以外(審査員名簿・GG賞紹介)を除外するためのキーワード。
EXCLUDE_PDF_KEYWORDS = ["judge", "審査員", "ＧＧ賞", "GG賞"]

FULL_PREF_NAMES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県", "静岡県",
    "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
    "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県",
    "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]
PREF_RE = re.compile("|".join(FULL_PREF_NAMES))
YEAR_TOKEN_RE = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")
AWARD_RE = re.compile(r"(金|銀|銅)(・[^\s\d]+)*")

ROW_START_RE = re.compile(r"^\d+\s")


def fetch_bytes(url):
    # PDFのURLは日本語ファイル名を含むため(例: 2024年採点結果（05甲州）.pdf)、
    # リクエスト前にパーセントエンコードする。
    safe_url = urllib.parse.quote(url, safe=":/")
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(safe_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
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


def pdf_to_text(pdf_bytes, tmp_path):
    tmp_path.write_bytes(pdf_bytes)
    result = subprocess.run(
        ["pdftotext", "-layout", str(tmp_path), "-"],
        capture_output=True, check=True,
    )
    return result.stdout.decode("utf-8")


def parse_award_pdf(text, year):
    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line or not ROW_START_RE.match(line):
            continue

        pref_match = None
        for m in PREF_RE.finditer(line):
            pref_match = m  # 行内最後の一致(醸造地列)を採用
        if not pref_match:
            continue

        award_match = AWARD_RE.search(line)
        if not award_match:
            continue

        before_pref = line[:pref_match.start()]
        year_matches = list(YEAR_TOKEN_RE.finditer(before_pref))
        if not year_matches:
            continue
        vintage_match = year_matches[-1]
        winery = before_pref[vintage_match.end():].strip()
        if not winery:
            continue

        records.append({
            "year": year,
            "pref": pref_match.group(0),
            "winery": winery,
            "gold": award_match.group(0).startswith("金"),
        })
    return records


def main():
    tmp_path = BASE_DIR / "_tmp_wine_award.pdf"
    all_records = []
    try:
        for i, year in enumerate(TARGET_YEARS, 1):
            archive_url = ARCHIVE_URL_TEMPLATE.format(year=year)
            print(f"[{i}/{len(TARGET_YEARS)}] {year}年度分を取得中... ({archive_url})")
            html_bytes = fetch_bytes(archive_url)
            if html_bytes is None:
                print("  -> アーカイブページが見つかりませんでした。スキップします。")
                continue
            html = html_bytes.decode("utf-8", errors="replace")
            pdf_urls = [u for u in re.findall(r'href="([^"]+\.pdf)"', html)
                        if not any(kw.lower() in u.lower() for kw in EXCLUDE_PDF_KEYWORDS)]
            pdf_urls = sorted(set(pdf_urls))
            print(f"  -> 対象PDF {len(pdf_urls)}件")

            year_records = []
            for pdf_url in pdf_urls:
                pdf_bytes = fetch_bytes(pdf_url)
                if pdf_bytes is None:
                    print(f"    (見つかりませんでした: {pdf_url})")
                    continue
                text = pdf_to_text(pdf_bytes, tmp_path)
                year_records += parse_award_pdf(text, year)
                time.sleep(REQUEST_DELAY_SECONDS)

            print(f"  -> {len(year_records)}件")
            all_records += year_records
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2)

    print()
    print(f"合計: {len(all_records)}件")
    print(f"出力先: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
