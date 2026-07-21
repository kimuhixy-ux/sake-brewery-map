#!/usr/bin/env python3
"""全国新酒鑑評会(独立行政法人酒類総合研究所(NRIB)・日本酒造組合中央会共催)の
入賞酒目録PDFを取得し、蔵ごとの受賞歴をsake_award_raw.jsonに保存する。

全国新酒鑑評会は100年以上続く最も権威のある清酒の公的コンテストで、入賞酒目録は
毎年PDFで公開されている(https://www.nrib.go.jp/data/kan/shinshu/award/)。
目録に載っている酒は全て「入賞酒」で、うち特に優秀なものに☆(金賞)が付く。

対象は令和7酒造年度(2025年度、最新)から平成28酒造年度(2016年度)までの直近10年分。
それ以前(平成14酒造年度まで遡れる)は、蔵の統廃合・名称変更が進み既存データとの
突合精度が下がるため対象外とした。

PDFはpdftotext -layoutで表形式のまま抽出できる(地ビールデータの取得と同じ手法)。
目録の各行は固定幅レイアウトになっているが、国税局・都道府県は同じグループの
先頭行にしか印字されない(2行目以降は空白)ため、直前の値を引き継ぐ
(forward-fill)必要がある。また列の間隔は都道府県名の文字数によって空白の
数が変わるため、スペース数による分割ではなく「先頭が国税局名/都道府県名か」を
判定して剥がす方式を取る。

法人番号(13桁の数字)を含む行だけが実データ行で、それ以外(タイトル・脚注・
ヘッダー再掲・空行)は無視する。

robots.txtにクロール制限は無いことを確認している。

標準ライブラリのみで書かれているが、pdftotextコマンド(poppler-utils)が
別途必要。
使い方: python3 scripts/scrape_sake_award_list.py
"""

import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_PATH = BASE_DIR / "sake_award_raw.json"

HEADERS = {"User-Agent": "sake-brewery-map/1.0 (personal PWA project; github.com/kimuhixy-ux/sake-brewery-map)"}
REQUEST_DELAY_SECONDS = 1.0
MAX_RETRIES = 3

# 対象10年度分。{PDFファイル名の接頭辞: 対応する西暦年}。
# 令和N年度 -> N+2018年度、平成N年度 -> N+1988年度。
TARGET_YEARS = {
    "r07": 2025, "r06": 2024, "r05": 2023, "r04": 2022, "r03": 2021,
    "r02": 2020, "r01": 2019,
    "h30": 2018, "h29": 2017, "h28": 2016,
}

PDF_URL_TEMPLATE = "https://www.nrib.go.jp/data/kan/shinshu/award/pdf/{prefix}by_moku.pdf"

# 国税局(表の左端の列。都道府県より先に剥がす必要がある)。
BUREAU_NAMES = [
    "関東信越", "札幌", "仙台", "東京", "金沢", "名古屋",
    "大阪", "広島", "高松", "福岡", "熊本", "沖縄",
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

# 目録本文では都道府県が「青森」「岩手」のように末尾の県/府/都/道を省略した
# 表記で印字される(北海道のみ元々省略の余地が無いためそのまま)。
# 短縮表記 -> 正式名称のマップを作り、こちらを先頭トークン判定に使う。
PREF_NAMES = sorted(
    ({name if name == "北海道" else name[:-1]: name for name in FULL_PREF_NAMES}).keys(),
    key=len, reverse=True,
)
PREF_SHORT_TO_FULL = {name if name == "北海道" else name[:-1]: name for name in FULL_PREF_NAMES}

CORP_ID_RE = re.compile(r"(.*?)\s*(\d{13})\s*(.*)")


def fetch_pdf_bytes(url):
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
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


def strip_leading_token(text, tokens):
    """textの先頭がtokens(国税局名 or 都道府県名)のいずれかで、直後が空白なら
    (一致したトークン, 取り除いた残り文字列)を返す。一致しなければNoneを返す。
    """
    for token in tokens:
        if text.startswith(token) and text[len(token):len(token) + 1].isspace():
            return token, text[len(token):].lstrip()
    return None


def parse_award_pdf(text, year):
    records = []
    current_pref = None
    for line in text.splitlines():
        m = CORP_ID_RE.match(line)
        if not m:
            continue
        before, _corp_id, after = m.groups()
        before = before.strip()
        if not before:
            continue

        gold = "☆" in after
        brand = after.replace("☆", "").strip()

        bureau_result = strip_leading_token(before, BUREAU_NAMES)
        if bureau_result is not None:
            _, before = bureau_result

        pref_result = strip_leading_token(before, PREF_NAMES)
        if pref_result is not None:
            short_pref, before = pref_result
            current_pref = PREF_SHORT_TO_FULL[short_pref]

        brewery = before.strip()
        if not brewery or not current_pref:
            continue

        records.append({
            "year": year,
            "pref": current_pref,
            "brewery": brewery,
            "brand": brand,
            "gold": gold,
        })
    return records


def main():
    tmp_path = BASE_DIR / "_tmp_award.pdf"
    all_records = []
    try:
        for i, (prefix, year) in enumerate(sorted(TARGET_YEARS.items(), key=lambda kv: -kv[1]), 1):
            url = PDF_URL_TEMPLATE.format(prefix=prefix)
            print(f"[{i}/{len(TARGET_YEARS)}] {year}年度分を取得中... ({url})")
            pdf_bytes = fetch_pdf_bytes(url)
            if pdf_bytes is None:
                print("  -> 見つかりませんでした。スキップします。")
                continue
            text = pdf_to_text(pdf_bytes, tmp_path)
            year_records = parse_award_pdf(text, year)
            print(f"  -> {len(year_records)}件")
            all_records += year_records
            time.sleep(REQUEST_DELAY_SECONDS)
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
