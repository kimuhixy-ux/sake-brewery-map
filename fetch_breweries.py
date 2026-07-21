#!/usr/bin/env python3
"""Overpass APIから日本全国の酒蔵の位置データを取得し、breweries.jsonを生成する。

標準ライブラリのみで書かれているので、pip installは不要。
使い方: python3 fetch_breweries.py
"""

import json
import math
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
MASTER_LIST_PATH = BASE_DIR / "master_list_geocoded.json"
BEER_MASTER_LIST_PATH = BASE_DIR / "beer_list_geocoded.json"

# Overpass APIのエンドポイント。第一候補がタイムアウト・エラーになったら
# 2番目のミラーサーバーに切り替える。
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
MAX_RETRIES = 3
RETRY_WAIT_SECONDS = 20
REQUEST_TIMEOUT_SECONDS = 200

# 泡盛は酒税法上「焼酎」の一種で、マスターリストのサイト側分類でも
# shochuに含まれる。泡盛は沖縄県産のみ(地理的表示保護)という前提で、
# category="shochu"かつpref="沖縄県"のものは"awamori"として区別する。
AWAMORI_PREF = "沖縄県"


def resolve_category(category, pref):
    if category == "shochu" and pref == AWAMORI_PREF:
        return "awamori"
    return category

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

# 蔵名が2文字以下(佐浦・菊姫など)の場合の誤マッチ防止に使うキーワード。
# match_sake_info() 参照。
BREWERY_KEYWORDS = ["酒造", "酒蔵", "銘醸", "醸造", "製造元", "工場"]

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
    "株式会社", "(株)", "（株）", "(株）", "㈱",
    "有限会社", "(有)", "（有）", "㈲",
    "合資会社", "(資)", "（資）", "㈾",
    "合名会社", "(名)", "（名）", "(名）", "㈴",
    "合同会社", "(同)", "（同）",
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
            except (OSError, json.JSONDecodeError) as e:
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

# 都道府県名(北海道以外)の末尾の「都・道・府・県」が省略された表記
# (例:「香川」)がまれにaddr:provinceにそのまま入力されていることがある。
# 都道府県プルダウンに正式名称と重複した項目が出ないよう正規化する。
FULL_PREF_NAMES_FOR_NORMALIZE = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県", "静岡県",
    "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
    "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県",
    "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]
SHORT_PREF_MAP = {name[:-1]: name for name in FULL_PREF_NAMES_FOR_NORMALIZE if name != "北海道"}


def normalize_pref(pref):
    """addr:provinceの値を日本語表記に正規化する。未知の値はそのまま返す。"""
    if not pref:
        return None
    pref = ROMAJI_PREF_MAP.get(pref, pref)
    return SHORT_PREF_MAP.get(pref, pref)


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

# OSMに全く登録がなく、Overpass検索では見つけられない蔵を手動で補うリスト。
# 座標は住所から調べた地区レベルの概算(施設ピンポイントの精度ではない)。
# 各エントリはsake_info.jsonの`brewery`と名称が一致する(または含む)ことを
# 前提にしており、match_sake_info()で通常のOSM由来レコードと同様に照合される。
MANUAL_ENTRIES = [
    {
        "name": "岩倉酒造場",
        "lat": 32.066707,
        "lon": 131.350980,
        "pref": "宮崎県",
        "address": "宮崎県西都市下三財7945",
        "website": None,
        "wikipedia": None,
        "category": "shochu",
    },
]

# 地ビール(クラフトビール)醸造所の検索・判定に使う語。
#
# OSM上ではcraft=brewery・microbrewery=yesのどちらのタグも、実際には
# ビールに限らず味噌・醤油の醸造所や、酒蔵(craft=breweryが誤用されている
# ケース)、さらにはmicrobrewery=yesが居酒屋・飲食店チェーンに誤って
# 付与されているとみられるケースまで混在することが実データ確認で分かった。
# タグの有無だけで判定すると味噌・醤油蔵や無関係な飲食店まで拾ってしまうため、
# 「名称にビール関連の語を含む」「product タグに beer が含まれる」の
# いずれかを満たす場合のみビール醸造所とみなす、名称優先の判定にする。
# この方式では、英語名などでビールを示す語を含まない実在のクラフトビール
# 醸造所(タグも product=beer が無いもの)を見逃す可能性があるが、
# 酒蔵側と同様にOSMの登録状況に依存する仕様であることを許容する。
# 「ビア」単体は「コロンビア」「オリビア」等と誤マッチするため含めない。
# 英単語も「hop」が「Shop」に誤マッチする等の事故があったため、
# 単語境界(\b)で挟んで完全な単語としてのみマッチさせる。
BEER_NAME_PATTERN = (
    "ビール|ブルワリー|ブリュワリー|ブルーイング|ブリューイング|"
    r"地ビール|クラフトビール|麦酒|ホップ|\bbeer\b|\bbrewery\b|\bbrewing\b|\bbr[äa]u\b|\bhop\b"
)
BEER_NAME_RE = re.compile(BEER_NAME_PATTERN, re.IGNORECASE)
SAKE_NAME_RE = re.compile(NAME_PATTERN)

# 名称の正規表現だけで全国検索すると、「アサヒビール」「キリンビール」を
# 名称に含むバス停、「ベビールーム(baby room)」のようにビールと無関係な
# 語にたまたま「ビール」が部分文字列として現れるもの、「ヒップホップ」
# 「〇〇ショップ」等、大量の無関係な地物まで拾ってしまうことが実データ確認で
# 分かった(酒蔵側のNAME_PATTERNと違い、ビール関連の語は無関係な語との
# 衝突が非常に多い)。そのため名称の全国検索は行わず、craft=brewery /
# microbrewery=yes のタグが付いた地物だけに範囲を絞り、その中で名称・
# productタグによる確認(is_beer_candidate)を行う方式にする。
BEER_QUERY = """
[out:json][timeout:170];
area["name"="日本"]["admin_level"="2"]->.jp;
(
  node["craft"="brewery"](area.jp);
  way["craft"="brewery"](area.jp);
  node["microbrewery"="yes"](area.jp);
  way["microbrewery"="yes"](area.jp);
);
out center tags;
"""

# 酒蔵側のMANUAL_ENTRIESと同じ用途。ビールは今のところ手動追加の必要が
# 見つかっていないため空だが、OSM未登録の醸造所に気づいた場合はここに追加する。
BEER_MANUAL_ENTRIES = []


def load_beer_master_list_records():
    """北山産業の全国クラフトビール醸造所リスト(scripts/scrape_beer_list.py +
    scripts/geocode_beer_list.pyで生成、beer_list_geocoded.json)を、
    OSM由来レコードと同じ形式に変換する。

    craft=brewery/microbrewery=yesタグだけでは全国で78件程度しか拾えず、
    業界推定(950件以上)にまったく届かないため、酒蔵側と同様に業界の
    公開リストを補完データとして使う。ジオコーディングに失敗した
    (lat/lonがNone)エントリは地図に表示できないため除外する。
    """
    if not BEER_MASTER_LIST_PATH.exists():
        return []
    with open(BEER_MASTER_LIST_PATH, encoding="utf-8") as f:
        entries = json.load(f)
    records = []
    for entry in entries:
        if entry.get("lat") is None or entry.get("lon") is None:
            continue
        records.append({
            "name": entry["name"],
            "lat": round(entry["lat"], 6),
            "lon": round(entry["lon"], 6),
            "pref": entry.get("pref"),
            "address": entry.get("address"),
            "website": None,
            "wikipedia": None,
            "category": "beer",
        })
    return records


def integrate_beer_master_list(osm_beer_records, master_beer_records):
    """ビールのマスターリストをOSM由来レコードに統合し、新規追加すべき
    レコードだけを返す(酒蔵側のintegrate_master_list()と同じ考え方だが、
    sake_info.json経由の突合が無い分シンプル)。

    正規化名+都道府県が一致するもの、あるいは都道府県が無いOSM
    レコードについては正規化名+座標の近さ(100km以内)が一致するものは、
    OSM側に既に存在するとみなして追加しない(二重ピン防止)。
    """
    by_name_pref = {}
    by_name_nopref = {}
    for r in osm_beer_records:
        norm = normalize_name(r["name"])
        if r.get("pref"):
            by_name_pref.setdefault((norm, r["pref"]), []).append(r)
        else:
            by_name_nopref.setdefault(norm, []).append(r)

    new_records = []
    for mr in master_beer_records:
        norm = normalize_name(mr["name"])
        dup_records = by_name_pref.get((norm, mr.get("pref")))
        if not dup_records:
            nopref_candidates = by_name_nopref.get(norm)
            if nopref_candidates:
                dup_records = [
                    r for r in nopref_candidates
                    if haversine_km(r["lat"], r["lon"], mr["lat"], mr["lon"]) <= NOPREF_MATCH_MAX_KM
                ] or None
        if dup_records:
            continue
        new_records.append(mr)
    return new_records


def is_beer_candidate(tags, name):
    """名称・productタグから、ビール醸造所とみなせるかどうかを判定する。"""
    product = tags.get("product", "")
    has_beer_product = any(p.strip().lower() == "beer" for p in product.split(";"))
    if SAKE_NAME_RE.search(name) and not has_beer_product:
        # 「酒造」「酒蔵」を含む名称は、product=beerで明示されない限り
        # 酒蔵(craft=breweryの誤用や、酒蔵が別事業でビールも造っているだけの
        # ケース)とみなし、ビール側には含めない。
        return False
    return bool(BEER_NAME_RE.search(name)) or has_beer_product


def build_beer_record(element):
    """1つのOSM要素からビール醸造所レコードを組み立てる。
    名称・座標が無い、またはビール醸造所と判定できない場合はNone。
    """
    tags = element.get("tags", {})
    name = tags.get("name")
    if not name:
        return None
    if not is_beer_candidate(tags, name):
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
        "category": "beer",
    }


def fetch_beer_elements():
    print("地ビール醸造所を検索します...")
    try:
        result = fetch_overpass(BEER_QUERY)
    except RuntimeError as e:
        print(f"地ビール検索に失敗しました(この分だけスキップして続行します): {e}")
        return []
    elements = result.get("elements", [])
    print(f"地ビール検索で{len(elements)}件の要素を取得しました。")
    return elements


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
        "_brand_verified": tags.get("_brand_verified") == "1",
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
        if r.get("_brand_verified"):
            base["_brand_verified"] = True
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


def load_master_list_records():
    """日本酒造組合中央会「酒蔵検索」を元にした全国清酒蔵元マスターリスト
    (scripts/scrape_master_list.py + scripts/geocode_master_list.pyで生成、
    master_list_geocoded.json)を、OSM由来レコードと同じ形式に変換する。

    OSMは登録者任せの網羅性しかなく、観光客向けの店舗を持たない小規模な
    蔵元は登録されないことが多いため、業界団体の公式リストを補完データとして
    使う。ジオコーディングに失敗した(lat/lonがNone)エントリは地図に
    表示できないため除外する。座標はNominatimによる住所検索の結果であり、
    OSM由来レコードと違って施設ピンポイントの精度ではない(市区町村〜字
    レベルの近似値であることが多い)。
    """
    if not MASTER_LIST_PATH.exists():
        return []
    with open(MASTER_LIST_PATH, encoding="utf-8") as f:
        entries = json.load(f)
    records = []
    for entry in entries:
        if entry.get("lat") is None or entry.get("lon") is None:
            continue
        records.append({
            "name": entry["name"],
            "lat": round(entry["lat"], 6),
            "lon": round(entry["lon"], 6),
            "pref": entry.get("pref"),
            "address": entry.get("address"),
            "website": None,
            "wikipedia": None,
            "category": resolve_category(entry.get("category", "sake"), entry.get("pref")),
            "_brand_verified": False,
        })
    return records


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# 都道府県情報の無いOSMレコードは正規化名のみで突き合わせるため、
# 「田中酒造」「上原酒造」のように同名だが無関係な蔵が全国の別々の
# 県に実在するケースで誤って同一視してしまう恐れがある。この経路の
# マッチだけは、OSM側とマスターリスト側の座標が近い(この距離未満)
# 場合に限って同一蔵とみなす(近似ジオコーディングの誤差を許容しつつ、
# 数百km離れた同名の別蔵を弾く)。
NOPREF_MATCH_MAX_KM = 100


def integrate_master_list(osm_records, master_records, sake_entries):
    """マスターリストをOSM由来レコードに統合し、新規追加すべきレコードだけを返す。

    正規化名+都道府県(都道府県が無いOSMレコードについては正規化名+
    座標の近さ)が一致するもの、あるいはsake_info.json経由で同一エントリに
    マッチするもの(例:「真澄」というブランド名のみのOSM登録と「宮坂醸造」
    というマスターリストの正式社名登録)は、OSM側に既に存在するとみなして
    追加しない(二重ピン防止)。

    OSM側は清酒/焼酎/泡盛を区別しておらず全レコードがデフォルトで"sake"
    扱いのため、上記の理由でマスターリスト側を除外する場合、そのマスター
    リストエントリがcategory="shochu"であれば対応するOSMレコードの
    categoryを"shochu"(沖縄県なら"awamori")に上書きする(OSM側にしか
    無い焼酎/泡盛蔵の見逃しを減らすため)。
    """
    by_name_pref = {}
    by_name_nopref = {}
    for r in osm_records:
        norm = normalize_name(r["name"])
        if r.get("pref"):
            by_name_pref.setdefault((norm, r["pref"]), []).append(r)
        else:
            by_name_nopref.setdefault(norm, []).append(r)

    by_sake_entry = {}
    for r in osm_records:
        trusted = r.get("_brand_verified", False)
        entry = match_sake_info(r["name"], r["pref"], sake_entries, trusted=trusted)
        if entry:
            by_sake_entry.setdefault((entry["brewery"], entry["pref"]), []).append(r)

    new_records = []
    for mr in master_records:
        norm = normalize_name(mr["name"])
        dup_records = by_name_pref.get((norm, mr.get("pref")))
        if not dup_records:
            nopref_candidates = by_name_nopref.get(norm)
            if nopref_candidates:
                dup_records = [
                    r for r in nopref_candidates
                    if haversine_km(r["lat"], r["lon"], mr["lat"], mr["lon"]) <= NOPREF_MATCH_MAX_KM
                ] or None
        if not dup_records:
            mentry = match_sake_info(mr["name"], mr.get("pref"), sake_entries, trusted=False)
            if mentry:
                dup_records = by_sake_entry.get((mentry["brewery"], mentry["pref"]))

        if dup_records:
            if mr["category"] != "sake":
                for r in dup_records:
                    r["category"] = mr["category"]
            continue

        new_records.append(mr)
    return new_records


def load_sake_info(path):
    """sake_info.jsonを読み込む。部分一致で突合するため辞書化はせずリストのまま返す。"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def match_sake_info(osm_name, osm_pref, sake_entries, trusted=False):
    """OSMの蔵名・都道府県から、sake_info.jsonの該当エントリを探す。

    OSM側は「白鶴酒造 灘魚崎工場」「菊正宗酒造記念館」のように、蔵名に
    支店・工場・資料館などの修飾語が付いていることが多いため、完全一致では
    なく正規化名同士の部分一致(どちらかがどちらかを含む)で判定する。
    また「獺祭」のようにOSM上でブランド名だけが登録されているケースに備え、
    銘柄名との完全一致も見る。
    同名の蔵が複数県に存在し候補が複数ある場合は、都道府県が一致するものを
    優先し、都道府県が分からず絞れない場合はマッチさせない(誤マッチ防止)。

    trusted=Trueは、craft=breweryタグ付きの要素(fetch_brand_match_elements経由)
    から呼ばれたことを示す。「舞姫」のように銘柄名が2文字以下だと、たまたま同名の
    無関係な施設(東京・福岡など)と完全一致してしまうことがあるため、短い銘柄名の
    完全一致はtrusted=Trueの場合のみ許可する。
    """
    osm_norm = normalize_name(osm_name)
    if not osm_norm:
        return None

    candidates = []
    for entry in sake_entries:
        brewery_norm = normalize_name(entry["brewery"])
        brand_norm = normalize_name(entry["brand"])
        contains_match = brewery_norm in osm_norm or osm_norm in brewery_norm
        # 「佐浦」「菊姫」のように蔵名が2文字以下だと、地名・施設名にたまたま
        # 同じ文字列が含まれるだけで誤マッチしやすい(例: 「伊佐浦川」「佐浦町」)。
        # そのため短い蔵名については、酒造関連の語も一緒に含まれている場合に限る。
        if contains_match and len(brewery_norm) <= 2:
            contains_match = any(kw in osm_norm for kw in BREWERY_KEYWORDS)
        exact_match = brand_norm == osm_norm
        if exact_match and len(brand_norm) <= 2 and not trusted:
            exact_match = False
        if contains_match or exact_match:
            candidates.append(entry)

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


def build_gap_query(sake_entries):
    """NAME_PATTERN(酒造|酒蔵|銘醸)では引っかからない蔵(月桂冠・八海醸造・
    一ノ蔵など、社名にその3語を含まない蔵)を追加で検索するためのクエリを作る。

    ブランド名は「真澄」「浦霞」のように地名・一般名詞と衝突し、Overpass側の
    検索が著しく重くなる(実測で504タイムアウトを引き起こした)ため含めない。
    社名のみを対象にし、1文字などの短すぎる名称も同様の理由で除外する。
    該当する蔵が無ければNoneを返す。
    """
    base_pattern = re.compile(NAME_PATTERN)
    terms = []
    seen = set()
    for entry in sake_entries:
        brewery = entry["brewery"]
        if base_pattern.search(brewery) or brewery in seen or len(brewery) < 2:
            continue
        seen.add(brewery)
        terms.append(re.escape(brewery))

    if not terms:
        return None

    pattern = "|".join(terms)
    return f"""
[out:json][timeout:170];
area["name"="日本"]["admin_level"="2"]->.jp;
(
  node["name"~"{pattern}"](area.jp);
  way["name"~"{pattern}"](area.jp);
);
out center tags;
"""


BRAND_MATCH_QUERY = """
[out:json][timeout:60];
area["name"="日本"]["admin_level"="2"]->.jp;
(
  node["craft"="brewery"](area.jp);
  way["craft"="brewery"](area.jp);
);
out center tags;
"""


def fetch_brand_match_elements(sake_entries):
    """「真澄」「獺祭」のように、OSM上で会社名ではなく銘柄名だけで登録されている
    蔵を拾うための検索。

    craft=brewery はビール・味噌・醤油の醸造所なども含む幅広いタグだが、
    日本全体で150件程度しかなく、名前の正規表現を使わないタグ検索なので
    高速(実測20秒未満)。ここでは全件取得したうえで、sake_info.jsonの
    蔵名・銘柄名のどちらかと一致するものだけを残すことで、ビール醸造所などの
    ノイズを地図に含めないようにする。
    """
    result = fetch_overpass(BRAND_MATCH_QUERY)
    candidates = result.get("elements", [])
    matched = []
    for el in candidates:
        if match_sake_info(el.get("tags", {}).get("name", ""), None, sake_entries, trusted=True):
            el.setdefault("tags", {})["_brand_verified"] = "1"
            matched.append(el)
    return matched


def main():
    if not SAKE_INFO_PATH.exists():
        print(f"エラー: {SAKE_INFO_PATH} が見つかりません。先にsake_info.jsonを用意してください。")
        sys.exit(1)

    sake_entries = load_sake_info(SAKE_INFO_PATH)

    try:
        result = fetch_overpass(OVERPASS_QUERY)
    except RuntimeError as e:
        print(f"エラー: {e}")
        sys.exit(1)

    elements = result.get("elements", [])
    print(f"Overpassから{len(elements)}件の要素を取得しました。")

    gap_query = build_gap_query(sake_entries)
    if gap_query:
        print("銘柄データにあるが「酒造/酒蔵/銘醸」を社名に含まない蔵を追加で検索します...")
        try:
            gap_result = fetch_overpass(gap_query)
            gap_elements = gap_result.get("elements", [])
            elements += gap_elements
            print(f"追加検索で{len(gap_elements)}件の要素を取得しました。")
        except RuntimeError as e:
            print(f"追加検索に失敗しました(この分だけスキップして続行します): {e}")

    print("銘柄名のみでOSMに登録されている蔵を追加で検索します...")
    try:
        brand_elements = fetch_brand_match_elements(sake_entries)
        elements += brand_elements
        print(f"銘柄名検索で{len(brand_elements)}件の蔵を追加しました。")
    except RuntimeError as e:
        print(f"銘柄名検索に失敗しました(この分だけスキップして続行します): {e}")

    print("取得した要素を整形します...")

    records = []
    for element in elements:
        record = build_record(element)
        if record:
            records.append(record)

    records = merge_duplicates(records)
    for r in records:
        r.setdefault("category", "sake")

    master_records = load_master_list_records()
    if master_records:
        new_master_records = integrate_master_list(records, master_records, sake_entries)
        print(f"マスターリスト{len(master_records)}件のうち、OSM未登録の{len(new_master_records)}件を追加します。")
        records += new_master_records

    records += [dict(entry) for entry in MANUAL_ENTRIES]

    beer_elements = fetch_beer_elements()
    beer_records = []
    for element in beer_elements:
        record = build_beer_record(element)
        if record:
            beer_records.append(record)
    beer_records = merge_duplicates(beer_records)

    beer_master_records = load_beer_master_list_records()
    if beer_master_records:
        new_beer_master_records = integrate_beer_master_list(beer_records, beer_master_records)
        print(f"地ビールのマスターリスト{len(beer_master_records)}件のうち、"
              f"OSM未登録の{len(new_beer_master_records)}件を追加します。")
        beer_records += new_beer_master_records

    beer_records += [dict(entry) for entry in BEER_MANUAL_ENTRIES]
    print(f"地ビール醸造所{len(beer_records)}件を追加します。")
    records += beer_records

    matched_count = 0
    for i, record in enumerate(records):
        record["id"] = i
        if record.get("category") == "beer":
            record.setdefault("featured", False)
            record.setdefault("brand", None)
            record.setdefault("desc", None)
            continue
        trusted = record.pop("_brand_verified", False)
        entry = match_sake_info(record["name"], record["pref"], sake_entries, trusted=trusted)
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
