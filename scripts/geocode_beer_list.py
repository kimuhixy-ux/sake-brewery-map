#!/usr/bin/env python3
"""beer_list_raw.jsonの各醸造所の住所をNominatim(OSM)でジオコーディングし、
緯度経度を付与してbeer_list_geocoded.jsonに保存する。

ロジックはscripts/geocode_master_list.pyと同じ(住所のクリーニング→
番地を段階的に削るフォールバック→行政区画境目へのスペース挿入)。
データソースが異なるだけなので、共通化はせずそのまま複製する。

標準ライブラリのみで書かれているので、pip installは不要。
使い方: python3 scripts/geocode_beer_list.py
"""

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_PATH = BASE_DIR / "beer_list_raw.json"
OUTPUT_PATH = BASE_DIR / "beer_list_geocoded.json"
CACHE_PATH = BASE_DIR / "beer_list_geocode_cache.json"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "sake-brewery-map/1.0 (personal PWA project; github.com/kimuhixy-ux/sake-brewery-map)"}
REQUEST_DELAY_SECONDS = 1.1
MAX_RETRIES = 3


def clean_address(raw):
    """〒番号・全角スペース・「(本社:〜)」のような補足情報を取り除く。"""
    addr = raw
    addr = re.sub(r"^〒\d{3}-?\d{4}\s*", "", addr)
    addr = re.sub(r"[（(][^（）()]*[）)]", "", addr)
    addr = addr.replace("　", " ").strip()
    return addr


def trim_levels(addr):
    """番地(数字-数字-数字など)を段階的に末尾から削り、町・字レベルまで
    フォールバック候補を生成する。
    """
    levels = [addr]
    trimmed = addr
    while True:
        new_trimmed = re.sub(r"[0-9０-９\-‐−ー]+\s*$", "", trimmed).strip()
        new_trimmed = re.sub(r"[番地号丁目条]\s*$", "", new_trimmed).strip()
        if new_trimmed == trimmed or not new_trimmed:
            break
        levels.append(new_trimmed)
        trimmed = new_trimmed
        if len(levels) >= 4:
            break

    m = re.match(r"^(.*?(?:市|区|町|村))", addr)
    if m and m.group(1) not in levels:
        levels.append(m.group(1))

    return levels


ADMIN_BOUNDARY_CHARS = "都道府県郡市区町村"


def insert_admin_spaces(addr):
    """都道府県・郡・市区町村の直後にスペースを挿入する。
    Nominatimの日本語住所検索は行政区画の境目にスペースが無いと
    正しく解析できず0件になることが多いため、区切りを明示した候補を
    優先的に試す。
    """
    chars = []
    for ch in addr:
        chars.append(ch)
        if ch in ADMIN_BOUNDARY_CHARS:
            chars.append(" ")
    spaced = re.sub(r"\s+", " ", "".join(chars)).strip()
    return spaced


def build_query_variants(addr):
    spaced = insert_admin_spaces(addr)
    if spaced != addr:
        return [spaced, addr]
    return [addr]


def nominatim_search(query):
    params = {"q": query, "format": "json", "countrycodes": "jp", "limit": 1}
    url = NOMINATIM_URL + "?" + urllib.parse.urlencode(params)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except (OSError, json.JSONDecodeError) as e:
            print(f"    失敗({attempt}回目): {e}")
            time.sleep(3)
    return []


def geocode_address(raw_address, cache):
    if raw_address in cache:
        return cache[raw_address]

    cleaned = clean_address(raw_address)
    levels = trim_levels(cleaned)

    result_entry = {"lat": None, "lon": None, "precision": "failed", "matched_query": None}
    found = False
    for i, level in enumerate(levels):
        for query in build_query_variants(level):
            results = nominatim_search(query)
            time.sleep(REQUEST_DELAY_SECONDS)
            if results:
                precision = "exact" if i == 0 else f"approx_level{i}"
                result_entry = {
                    "lat": float(results[0]["lat"]),
                    "lon": float(results[0]["lon"]),
                    "precision": precision,
                    "matched_query": query,
                }
                found = True
                break
        if found:
            break

    cache[raw_address] = result_entry
    return result_entry


def main():
    with open(INPUT_PATH, encoding="utf-8") as f:
        entries = json.load(f)

    cache = {}
    if CACHE_PATH.exists():
        with open(CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)
        print(f"キャッシュを読み込みました({len(cache)}件)。")

    results = []
    for i, entry in enumerate(entries, 1):
        needs_fetch = entry["address"] not in cache
        geo = geocode_address(entry["address"], cache)
        record = dict(entry)
        record.update(geo)
        results.append(record)

        if needs_fetch or i % 50 == 0:
            print(f"[{i}/{len(entries)}] {entry['name']} ({entry['pref']}) -> "
                  f"{geo['precision']} lat={geo['lat']} lon={geo['lon']}")

        if i % 20 == 0:
            with open(CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)

    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    failed = sum(1 for r in results if r["precision"] == "failed")
    exact = sum(1 for r in results if r["precision"] == "exact")
    approx = len(results) - failed - exact
    print()
    print(f"合計: {len(results)}件 (exact={exact}件, approx={approx}件, failed={failed}件)")
    print(f"出力先: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
