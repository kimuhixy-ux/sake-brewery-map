#!/usr/bin/env python3
"""北山産業(Kita Sangyo Co., Ltd)が公開している全国クラフトビール
(地ビール・地発泡酒)醸造所リストのPDF(地域別10ファイル + 年別新規開業
リスト4ファイル)から、醸造所名・都道府県・住所を抽出し、
beer_list_raw.jsonに保存する。

OSM(Overpass API)のcraft=brewery/microbrewery=yesタグだけでは全国で
78件程度しか拾えず、業界推定(950件以上)の1割にも満たないことが分かった
ため、酒蔵側(日本酒造組合中央会マスターリスト)と同様に業界の公開リストを
一次情報源として使う。北山産業はビール醸造設備メーカーとして業界内で
広く知られており、このリストは長期間継続的に更新されている。

robots.txtにクロール制限は無く、PDF内の著作権表示も標準的な
「All Rights Reserved」のみで、事実データ(蔵名・住所等)の再利用を
明確に禁じる記載は無いことを確認している。解説文などの著作物は
複製せず、名称・都道府県・住所といった事実情報のみを抽出する。

地域別10ファイルのうち6地域(北海道・北陸・近畿・中国・四国・信越)は
「データ更新：2021年12月末時点」のまま更新されておらず、2022年以降に
開業した醸造所が抜け落ちている。これを補うため、北山産業が別途公開して
いる年別(2022〜2025年)の全国新規開業リストも合わせて取得する。
备考欄に「閉店」「閉鎖」「業務終了」等の記載がある行(廃業した醸造所)は
除外する。

PDFのテキスト抽出にはpoppler-utilsのpdftotextコマンドを使う
(Python本体は標準ライブラリのみだが、この外部コマンドだけは必須。
 未インストールの場合は `brew install poppler` 等でインストールする)。

使い方: python3 scripts/scrape_beer_list.py
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_PATH = BASE_DIR / "beer_list_raw.json"

HEADERS = {"User-Agent": "sake-brewery-map/1.0 (personal PWA project; github.com/kimuhixy-ux/sake-brewery-map)"}
REQUEST_DELAY_SECONDS = 1.0
MAX_RETRIES = 3

# https://kitasangyo.com/beer/MAP.html に掲載されている地域別PDF(10ファイル)。
# ファイル名の日付は地域によって「データ更新」時点が異なり、東北・関東・
# 東海・九州沖縄は2026年6月24日更新済みだが、それ以外は2021年12月末時点で
# 止まっている(下記YEARLY_SUPPLEMENT_PDF_URLSで補う)。
REGIONAL_PDF_URLS = [
    "https://kitasangyo.com/pdf/craftbeer/202302_hokkaido.pdf",
    "https://kitasangyo.com/pdf/craftbeer/260624_tohoku.pdf",
    "https://kitasangyo.com/pdf/craftbeer/202302_shinetsu.pdf",
    "https://kitasangyo.com/pdf/craftbeer/260624_kanto.pdf",
    "https://kitasangyo.com/pdf/craftbeer/260624_tokai.pdf",
    "https://kitasangyo.com/pdf/craftbeer/202302_hokuriku.pdf",
    "https://kitasangyo.com/pdf/craftbeer/202302_kinki.pdf",
    "https://kitasangyo.com/pdf/craftbeer/202303_chugoku.pdf",
    "https://kitasangyo.com/pdf/craftbeer/202302_shikoku.pdf",
    "https://kitasangyo.com/pdf/craftbeer/260624_kyushu.pdf",
]

# 地域別リストが2021年12月末時点で止まっている地域を補うための、
# 年別(全国)新規開業リスト。2023年分は「開業・閉店」両方を含む版
# (2023-open_202407.pdf)の方が閉店情報も網羅的なため、単純な
# open_2023_2407.pdfではなくこちらを使う。
YEARLY_SUPPLEMENT_PDF_URLS = [
    "https://kitasangyo.com/beer/open_2022_2407.pdf",
    "https://kitasangyo.com/pdf/craftbeer/2023-open_202407.pdf",
    "https://kitasangyo.com/pdf/craftbeer/2024Open_craftbrewery.pdf",
    "https://kitasangyo.com/pdf/craftbeer/2025Open_craftbrewery.pdf",
]

# 都道府県の正式名称(scripts/scrape_master_list.pyのPREF_SLUGSと同じ47件)。
FULL_PREF_NAMES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県", "静岡県",
    "愛知県",
    "三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
    "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県",
    "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]

# PDF内では都道府県が「都道府県」の末尾1文字を落とした短縮形で表記される
# (例:「茨城」「東京」「大阪」)。北海道だけは「道」を含む正式名称がそのまま
# 使われる(短縮すると「北海」になり誤りのため)。
SHORT_TO_FULL_PREF = {}
for _full in FULL_PREF_NAMES:
    if _full == "北海道":
        SHORT_TO_FULL_PREF["北海道"] = "北海道"
    else:
        SHORT_TO_FULL_PREF[_full[:-1]] = _full

PREF_TOKEN_RE = re.compile(
    r"^(" + "|".join(sorted(SHORT_TO_FULL_PREF.keys(), key=len, reverse=True)) + r")\s+(.*)$"
)

# 開業時期(YYYYMM)を行内のアンカーとして使い、それより前を企業名・
# ブランド名欄、後を住所欄とみなす。西暦1900〜2099年に限定して、
# 住所・電話番号中の別の6桁の数字列と誤認しないようにする。
YYYYMM_RE = re.compile(r"(?<!\d)(19|20)\d{4}(?!\d)")

# 住所欄の直後に来る電話番号(市外局番-市内局番-番号)、または電話番号が
# 無い場合の"NA"表記。これが現れた位置で住所欄を打ち切る。
PHONE_OR_NA_RE = re.compile(r"\d{1,5}-\d{1,4}-\d{2,5}|\bNA\b")

# 備考欄にこれらの語があれば、廃業済みとみなしてレコードごと除外する。
# (北山産業のPDFは廃業した醸造所も「〇年に閉店したブルワリー」として
# 別枠で追記することがあるが、その行自体も同じ表形式のため通常の行として
# 拾ってしまう。備考欄の文言で除外することで両方に対応する。)
CLOSURE_KEYWORDS = ["閉店", "閉鎖", "業務終了", "事業停止", "生産休止", "免許返納", "休業中"]


def check_pdftotext_available():
    if shutil.which("pdftotext") is None:
        print(
            "エラー: pdftotextコマンドが見つかりません。"
            "poppler-utilsが必要です(例: brew install poppler)。",
            file=sys.stderr,
        )
        sys.exit(1)


def fetch_pdf_text(url):
    """PDFをダウンロードしてpdftotext -layoutでテキスト化する。"""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                pdf_bytes = resp.read()
            break
        except (urllib.error.URLError, OSError) as e:
            last_error = e
            print(f"  失敗({attempt}回目): {e}")
            time.sleep(3)
    else:
        raise RuntimeError(f"取得に失敗しました: {url} ({last_error})")

    with tempfile.NamedTemporaryFile(suffix=".pdf") as pdf_file:
        pdf_file.write(pdf_bytes)
        pdf_file.flush()
        result = subprocess.run(
            ["pdftotext", "-layout", pdf_file.name, "-"],
            capture_output=True, check=True,
        )
        return result.stdout.decode("utf-8", errors="replace")


def parse_pdf_text(text, source_label):
    """pdftotext -layoutで抽出したテキストから醸造所レコードを取り出す。"""
    records = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        m = PREF_TOKEN_RE.match(stripped)
        if not m:
            continue
        pref_short, rest = m.group(1), m.group(2)

        ym_match = YYYYMM_RE.search(rest)
        if not ym_match:
            # 県名だけの見出し行や、ヘッダー("県名 企業名 ブランド名..."等)。
            continue

        name_blob = rest[:ym_match.start()].strip()
        remainder = rest[ym_match.end():]
        if not name_blob:
            continue

        if any(kw in line for kw in CLOSURE_KEYWORDS):
            continue

        segments = [s.strip() for s in re.split(r"\s{2,}", name_blob) if s.strip()]
        if not segments:
            continue
        # 企業名だけの列、または企業名+ブランド名(+施設名)の複数列がある場合、
        # 最も具体的で認知度の高いブランド名(最後の列)を名称として使う。
        name = segments[-1]

        addr_match = PHONE_OR_NA_RE.search(remainder)
        address = remainder[:addr_match.start()].strip() if addr_match else remainder.strip()
        if not address:
            continue

        pref_full = SHORT_TO_FULL_PREF[pref_short]
        if not address.startswith(pref_full):
            address = pref_full + address

        records.append({
            "name": name,
            "pref": pref_full,
            "address": address,
            "category": "beer",
            "source": source_label,
        })
    return records


def main():
    check_pdftotext_available()

    all_records = []
    urls = REGIONAL_PDF_URLS + YEARLY_SUPPLEMENT_PDF_URLS
    for i, url in enumerate(urls, 1):
        label = Path(url).stem
        print(f"[{i}/{len(urls)}] {label} を取得中...")
        text = fetch_pdf_text(url)
        records = parse_pdf_text(text, label)
        print(f"  -> {len(records)}件")
        all_records.extend(records)
        time.sleep(REQUEST_DELAY_SECONDS)

    # 地域別リストと年別リストの間で同じ醸造所が重複することがあるため、
    # (正規化した名称, 都道府県)が完全一致するものは1件にまとめる。
    # 名称の会社形態表記ゆれの正規化はfetch_breweries.py側で改めて行うため、
    # ここでは単純な空白除去のみで重複排除する。
    seen = {}
    deduped = []
    for r in all_records:
        # 「B.M.B Brewery」「B･M･B Brewery」のように、同じ醸造所が
        # 半角ピリオドと全角中点の表記ゆれだけで別レコードになることが
        # あるため、記号・空白を除去し大文字小文字を無視して突合する。
        normalized = re.sub(r"[\s.\-−ー・･,，、()（）\[\]/]+", "", r["name"]).lower()
        key = (normalized, r["pref"])
        if key in seen:
            continue
        seen[key] = True
        deduped.append(r)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)

    print()
    print(f"合計: {len(all_records)}件 (重複排除後 {len(deduped)}件)")
    print(f"出力先: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
