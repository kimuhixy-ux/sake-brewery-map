#!/usr/bin/env python3
"""Overpass APIから日本全国の酒蔵の位置データを取得し、breweries.jsonを生成する。

標準ライブラリのみで書かれているので、pip installは不要。
使い方: python3 fetch_breweries.py
"""

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SAKE_INFO_PATH = BASE_DIR / "sake_info.json"
OUTPUT_PATH = BASE_DIR / "breweries.json"

# Overpass APIのエンドポイント。第一候補がタイムアウト・エラーになったら
# 2番目のミラーサーバーに切り替える。
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
MAX_RETRIES = 3
RETRY_WAIT_SECONDS = 20
REQUEST_TIMEOUT_SECONDS = 200

HEADERS = {"User-Agent": "sake-brewery-map/1.0 (personal PWA project)"}

# craft=sake_brewery が本命タグだが、実際のOSMデータではほぼ使われていない。
# craft=brewery で登録されている蔵も一部あるが、それだけでは有名な蔵の大半が
# 拾えないことが分かった(獺祭=旭酒造や八海山=八海醸造などはshop=alcoholや
# landuse=industrialなど、様々なタグで登録されている)。
#
# そこで、craft=sake_brewery を個別に拾いつつ、それ以外は「タグの種類を問わず
# 名称に酒造・酒蔵・銘醸を含む施設」を全国から検索する方針にする。
# 試した結果、["landuse"="industrial"]["name"~...] のように、件数の多いキーで
# 絞り込んでから名称の正規表現をかける書き方はOverpass側の処理が重く、
# 180秒のタイムアウトに収まらなかった。一方、["name"~...] だけで(他のキーを
# 指定せず)nameインデックスを使って検索すると、同じ範囲でも数十秒で完了する。
# そのため、この「name単独検索」方式を採用する。
# 「本家」はラーメン店等の店名にも頻出し曖昧なため、検索キーワードからは外した。
NAME_PATTERN = "酒造|酒蔵|銘醸"

OVERPASS_QUERY = f"""
[out:json][timeout:170];
area["name"="日本"]["admin_level"="2"]->.jp;
(
  node["craft"="sake_brewery"](area.jp);
  way["craft"="sake_brewery"](area.jp);
  relation["craft"="sake_brewery"](area.jp);
  node["name"~"{NAME_PATTERN}"](area.jp);
  way["name"~"{NAME_PATTERN}"](area.jp);
);
out center tags;
"""

# 名称に含まれがちな会社形態の表記や空白を取り除いて、突合しやすい形にそろえる。
COMPANY_FORMS = [
    "株式会社", "(株)", "（株）",
    "有限会社", "(有)", "（有）",
    "合資会社", "合名会社",
]


def normalize_name(name):
    """蔵の名称を突合用に正規化する(会社形態の表記ゆれ・空白を除去)。"""
    if not name:
        return ""
    normalized = name
    for form in COMPANY_FORMS:
        normalized = normalized.replace(form, "")
    normalized = re.sub(r"\s+", "", normalized)
    return normalized.strip()


def fetch_overpass(query):
    """Overpass APIにクエリを投げる。失敗時は待って再試行し、
    それでもダメなら次のミラーサーバーに切り替える。
    """
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    last_error = None

    for url in OVERPASS_URLS:
        for attempt in range(1, MAX_RETRIES + 1):
            print(f"Overpass APIへ問い合わせ中... ({url} / 試行{attempt}回目)")
            try:
                req = urllib.request.Request(url, data=data, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                    body = resp.read()
                return json.loads(body)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                last_error = e
                print(f"  失敗しました: {e}")
                if attempt < MAX_RETRIES:
                    print(f"  {RETRY_WAIT_SECONDS}秒待って再試行します...")
                    time.sleep(RETRY_WAIT_SECONDS)
        print(f"{url} を諦めて、次の候補があれば切り替えます...")

    raise RuntimeError(
        f"Overpass APIからのデータ取得に失敗しました(最後のエラー: {last_error})。"
        "時間をおいて再実行するか、ネットワーク接続を確認してください。"
    )


def get_center(element):
    """node/way/relationのどれでも、代表となる緯度経度を返す。"""
    if element.get("type") == "node":
        return element.get("lat"), element.get("lon")
    center = element.get("center")
    if center:
        return center.get("lat"), center.get("lon")
    return None, None


# addr:province はほとんどが日本語(例: "岐阜県")だが、まれにローマ字表記
# (例: "Gifu")で入力されているケースがある。都道府県プルダウンで表記が
# 揺れないよう、代表的なローマ字表記だけ日本語に正規化する。
ROMAJI_PREF_MAP = {
    "Gifu": "岐阜県", "Gifu-ken": "岐阜県",
    "Hokkaido": "北海道", "Hokkaidō": "北海道",
    "Kyoto": "京都府", "Osaka": "大阪府", "Tokyo": "東京都",
}


def normalize_pref(pref):
    """addr:provinceの値を日本語表記に正規化する。未知の値はそのまま返す。"""
    if not pref:
        return None
    return ROMAJI_PREF_MAP.get(pref, pref)


def build_address(tags):
    """addr:full があればそれを、無ければ addr:* を並べて連結する。"""
    full = tags.get("addr:full")
    if full:
        return full
    keys_in_order = [
        "addr:province", "addr:city", "addr:suburb",
        "addr:quarter", "addr:neighbourhood",
        "addr:street", "addr:block_number", "addr:housenumber",
    ]
    parts = [tags[k] for k in keys_in_order if tags.get(k)]
    return "".join(parts) if parts else None


def build_wikipedia_url(tags):
    """"ja:記事名" 形式のwikipediaタグをURLに変換する。"""
    wiki = tags.get("wikipedia")
    if not wiki:
        return None
    if ":" in wiki:
        lang, title = wiki.split(":", 1)
    else:
        lang, title = "ja", wiki
    title = title.strip()
    if not title:
        return None
    quoted = urllib.parse.quote(title.replace(" ", "_"))
    return f"https://{lang}.wikipedia.org/wiki/{quoted}"


# 名称キーワード一致だけで拾うと、居酒屋・飲食店(店名に「酒蔵」を含むことがある)が
# 紛れ込むことがあるため、これらのamenityタグが付いている場合は除外する。
EXCLUDE_AMENITIES = {"restaurant", "bar", "pub", "cafe", "fast_food", "izakaya", "nightclub"}

# 「酒蔵通り」のような地名・施設名の一部として「酒蔵」を含むだけの、
# 明らかに酒蔵そのものではない施設(住宅展示場など)を除外するキーワード。
NOISE_NAME_KEYWORDS = ["住宅公園", "ハウジング", "ドライブイン"]


def build_record(element):
    """1つのOSM要素から酒蔵レコードを組み立てる。名称や座標が無ければNone。
    居酒屋・飲食店や、明らかに酒蔵ではない施設とみられるものも除外する。
    """
    tags = element.get("tags", {})
    name = tags.get("name")
    if not name:
        return None
    if tags.get("amenity") in EXCLUDE_AMENITIES:
        return None
    if any(kw in name for kw in NOISE_NAME_KEYWORDS):
        return None
    lat, lon = get_center(element)
    if lat is None or lon is None:
        return None
    return {
        "name": name,
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "pref": normalize_pref(tags.get("addr:province")),
        "address": build_address(tags),
        "website": tags.get("website") or tags.get("contact:website"),
        "wikipedia": build_wikipedia_url(tags),
    }


def merge_cluster(cluster):
    """同一施設とみなされた複数レコードを1件にまとめる。
    各項目は最初に見つかった値を採用しつつ、空欄なら後続レコードの値で埋める。
    """
    base = dict(cluster[0])
    for r in cluster[1:]:
        for key in ("pref", "address", "website", "wikipedia"):
            if not base.get(key) and r.get(key):
                base[key] = r[key]
        if r.get("name") and len(r["name"]) > len(base.get("name") or ""):
            base["name"] = r["name"]
    return base


def merge_duplicates(records):
    """複数のタグ種別(craft/shop/landuse/buildingなど)で同じ蔵が
    重複して取得されることがあるため、正規化名称が同じで座標も近い
    (緯度経度差0.01度、約1km以内)レコードを同一施設とみなして統合する。
    """
    by_name = {}
    for r in records:
        by_name.setdefault(normalize_name(r["name"]), []).append(r)

    merged = []
    for group in by_name.values():
        clusters = []
        for r in group:
            placed_cluster = None
            for cluster in clusters:
                rep = cluster[0]
                if abs(rep["lat"] - r["lat"]) < 0.01 and abs(rep["lon"] - r["lon"]) < 0.01:
                    placed_cluster = cluster
                    break
            if placed_cluster is not None:
                placed_cluster.append(r)
            else:
                clusters.append([r])
        for cluster in clusters:
            merged.append(merge_cluster(cluster))
    return merged


def load_sake_info(path):
    """sake_info.jsonを読み込み、正規化した蔵名をキーにした辞書にする。
    同名蔵が複数県にある場合に備え、値はリストにしておく。
    """
    with open(path, encoding="utf-8") as f:
        entries = json.load(f)
    by_name = {}
    for entry in entries:
        norm = normalize_name(entry["brewery"])
        by_name.setdefault(norm, []).append(entry)
    return by_name


def match_sake_info(osm_name, osm_pref, sake_by_name):
    """OSMの蔵名・都道府県から、sake_info.jsonの該当エントリを探す。
    同名の蔵が複数県に存在する場合は、都道府県が一致するものだけを採用し、
    都道府県が分からず候補を絞れない場合はマッチさせない(誤マッチ防止)。
    """
    candidates = sake_by_name.get(normalize_name(osm_name))
    if not candidates:
        return None
    if len(candidates) == 1:
        entry = candidates[0]
        if osm_pref and entry["pref"] != osm_pref:
            return None
        return entry
    if osm_pref:
        for entry in candidates:
            if entry["pref"] == osm_pref:
                return entry
    return None


def main():
    if not SAKE_INFO_PATH.exists():
        print(f"エラー: {SAKE_INFO_PATH} が見つかりません。先にsake_info.jsonを用意してください。")
        sys.exit(1)

    sake_by_name = load_sake_info(SAKE_INFO_PATH)

    try:
        result = fetch_overpass(OVERPASS_QUERY)
    except RuntimeError as e:
        print(f"エラー: {e}")
        sys.exit(1)

    elements = result.get("elements", [])
    print(f"Overpassから{len(elements)}件の要素を取得しました。整形します...")

    records = []
    for element in elements:
        record = build_record(element)
        if record:
            records.append(record)

    records = merge_duplicates(records)

    matched_count = 0
    for i, record in enumerate(records):
        record["id"] = i
        entry = match_sake_info(record["name"], record["pref"], sake_by_name)
        if entry:
            record["featured"] = True
            record["brand"] = entry["brand"]
            record["desc"] = entry["desc"]
            matched_count += 1
        else:
            record["featured"] = False
            record["brand"] = None
            record["desc"] = None

    records.sort(key=lambda r: (r["pref"] or "", r["name"]))
    # ソート後にidを振り直す(表示順と一致させる)。
    for i, record in enumerate(records):
        record["id"] = i

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print()
    print(f"取得件数: {len(records)}件")
    print(f"銘柄情報がマッチした件数: {matched_count}件")
    print(f"出力先: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
