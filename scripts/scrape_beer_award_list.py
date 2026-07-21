#!/usr/bin/env python3
"""インターナショナル・ビアカップ(IBC、日本地ビール協会/Craft Beer Association
(CBA)主催、1996年創設)の受賞結果PDFを取得し、醸造所ごとの受賞歴を
beer_award_raw.jsonに保存する(全国新酒鑑評会に対するsake_award_raw.json、
日本ワインコンクールに対するwine_award_raw.jsonと同じ位置づけ)。

IBCはbeertaster.org/medal/ibc{年}_award.pdf という命名規則でほぼ毎年のPDFを
公開している。ただし2018年のみ命名が異なり、"ibc2018_award.pdf"は誤って
2019年の内容を返す(サーバー側の重複ファイルとみられる)ため、2018年度は
"ibc2018_award_m.pdf"を使う。

PDFは日英併記の受賞ビール一覧で、1エントリにつき次の3行が(間に空行や
右寄せの醸造責任者名の行を挟みつつ)この順で現れる:
  1. 日本語行: 出品者(会社名)/醸造所名/ブランド名/ビール名 のあと、
     国内の出品者のみ最後に都道府県名が付く(海外の出品者は国名になる)。
  2. 英語行: 同じ項目の英語表記(海外の出品者は日本語行と同一内容になる)。
  3. 賞(GOLD/SILVER/BRONZE、和文行では金賞/銀賞/銅賞)。

賞の付き方は年度によってレイアウトが異なり、
  - 2018年以前: 日本語行・英語行の各行の先頭に賞名が直接付く
    (例: " 銀賞       麗人酒造株式会社  ...")
  - 2019年以降: 賞は日本語行・英語行の後に独立した行として現れる
    (例: " GOLD" だけの行)
という2パターンが混在する。本スクリプトはこの違いを吸収するため、
「都道府県名を含む行だけを国内出品者の行として扱う」方式を取る
(海外出品者の行は国名しか出ないため自動的に無視される)。国内出品者の行に
賞名が先頭に付いていればその場で確定し、付いていなければ後続の行から
最初に現れる賞マーカー(独立行のGOLD/SILVER/BRONZE、または和文の
金賞/銀賞/銅賞)を探して確定する。

対象は2025年(最新)から2016年までの直近10年分。この範囲は全てPDFが
存在することを確認済み(1996年から続く長い歴史の一部)。

robots.txtにクロール制限は無いことを確認している。

標準ライブラリのみで書かれているが、pdftotextコマンド(poppler-utils)が
別途必要。
使い方: python3 scripts/scrape_beer_award_list.py
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
OUTPUT_PATH = BASE_DIR / "beer_award_raw.json"

HEADERS = {"User-Agent": "sake-brewery-map/1.0 (personal PWA project; github.com/kimuhixy-ux/sake-brewery-map)"}
REQUEST_DELAY_SECONDS = 1.0
MAX_RETRIES = 3

PDF_URL_TEMPLATE = "http://beertaster.org/medal/ibc{year}_award.pdf"
# 2018年度だけ"ibc2018_award.pdf"が誤って2019年度分を返すため、別名を使う。
PDF_URL_OVERRIDES = {
    2018: "http://beertaster.org/medal/ibc2018_award_m.pdf",
}

TARGET_YEARS = [2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018, 2017, 2016]

FULL_PREF_NAMES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県", "静岡県",
    "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
    "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県",
    "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]
# IBCの表内では都道府県が「東京」「長野」のように末尾の県/府/都/道を省略した
# 表記で印字される(北海道のみ元々省略の余地が無い)。
PREF_SHORT_TO_FULL = {name if name == "北海道" else name[:-1]: name for name in FULL_PREF_NAMES}
PREF_RE = re.compile("|".join(sorted(PREF_SHORT_TO_FULL.keys(), key=len, reverse=True)))

AWARD_PREFIX_RE = re.compile(r"^\s*(金賞|銀賞|銅賞)\s+")
AWARD_STANDALONE_RE = re.compile(r"^\s*(GOLD|SILVER|BRONZE|金賞|銀賞|銅賞)\s*$")
GOLD_TOKENS = {"GOLD", "金賞"}

COLUMN_SPLIT_RE = re.compile(r"\s{2,}")


def fetch_bytes(url):
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


def parse_award_pdf(text, year):
    records = []
    pending = None  # {"brewery": str, "pref": str} while waiting for award marker

    for line in text.splitlines():
        if not line.strip():
            continue

        standalone_m = AWARD_STANDALONE_RE.match(line)
        if standalone_m:
            if pending is not None:
                records.append({
                    "year": year,
                    "pref": pending["pref"],
                    "brewery": pending["brewery"],
                    "gold": standalone_m.group(1) in GOLD_TOKENS,
                })
                pending = None
            continue

        pref_m = PREF_RE.search(line)
        if not pref_m:
            continue

        prefix_m = AWARD_PREFIX_RE.match(line)
        rest = line[prefix_m.end():] if prefix_m else line
        fields = COLUMN_SPLIT_RE.split(rest.strip())
        brewery = fields[0].strip() if fields else ""
        if not brewery:
            continue
        pref = PREF_SHORT_TO_FULL[pref_m.group(0)]

        if prefix_m:
            records.append({
                "year": year,
                "pref": pref,
                "brewery": brewery,
                "gold": prefix_m.group(1) == "金賞",
            })
        else:
            # 賞名がこの行に無い場合は、後続の独立した賞マーカー行を待つ。
            pending = {"brewery": brewery, "pref": pref}

    return records


def main():
    tmp_path = BASE_DIR / "_tmp_beer_award.pdf"
    all_records = []
    try:
        for i, year in enumerate(TARGET_YEARS, 1):
            url = PDF_URL_OVERRIDES.get(year, PDF_URL_TEMPLATE.format(year=year))
            print(f"[{i}/{len(TARGET_YEARS)}] {year}年分を取得中... ({url})")
            pdf_bytes = fetch_bytes(url)
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
