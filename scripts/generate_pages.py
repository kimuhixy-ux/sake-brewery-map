#!/usr/bin/env python3
"""Generate bilingual, fact-only brewery and winery pages."""

from __future__ import annotations

import html
import json
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from string import Template
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://kimuhixy.com/sake-brewery-map"
OG_IMAGE = f"{BASE}/icons/icon-512.png"
CATEGORY_JA = {"sake": "清酒", "shochu": "焼酎", "awamori": "泡盛", "beer": "地ビール", "wine": "ワイン"}
CATEGORY_EN = {"sake": "Sake Brewery", "shochu": "Shochu Distillery", "awamori": "Awamori Distillery", "beer": "Craft Brewery", "wine": "Winery"}
COMPETITION_JA = {"sake": "全国新酒鑑評会", "wine": "日本ワインコンクール", "beer": "インターナショナル・ビアカップ"}
COMPETITION_EN = {"sake": "National New Sake Appraisal", "wine": "Japan Wine Competition", "beer": "International Beer Cup"}
PREF_EN = {
    "北海道": "Hokkaido", "青森県": "Aomori", "岩手県": "Iwate", "宮城県": "Miyagi", "秋田県": "Akita", "山形県": "Yamagata", "福島県": "Fukushima",
    "茨城県": "Ibaraki", "栃木県": "Tochigi", "群馬県": "Gunma", "埼玉県": "Saitama", "千葉県": "Chiba", "東京都": "Tokyo", "神奈川県": "Kanagawa",
    "新潟県": "Niigata", "富山県": "Toyama", "石川県": "Ishikawa", "福井県": "Fukui", "山梨県": "Yamanashi", "長野県": "Nagano", "岐阜県": "Gifu",
    "静岡県": "Shizuoka", "愛知県": "Aichi", "三重県": "Mie", "滋賀県": "Shiga", "京都府": "Kyoto", "大阪府": "Osaka", "兵庫県": "Hyogo",
    "奈良県": "Nara", "和歌山県": "Wakayama", "鳥取県": "Tottori", "島根県": "Shimane", "岡山県": "Okayama", "広島県": "Hiroshima", "山口県": "Yamaguchi",
    "徳島県": "Tokushima", "香川県": "Kagawa", "愛媛県": "Ehime", "高知県": "Kochi", "福岡県": "Fukuoka", "佐賀県": "Saga", "長崎県": "Nagasaki",
    "熊本県": "Kumamoto", "大分県": "Oita", "宮崎県": "Miyazaki", "鹿児島県": "Kagoshima", "沖縄県": "Okinawa",
}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def load_data() -> tuple[list[dict], dict[str, dict]]:
    records = json.loads((ROOT / "breweries.json").read_text(encoding="utf-8"))
    overlay = json.loads((ROOT / "data/featured-en.json").read_text(encoding="utf-8"))
    required = {"id", "name", "lat", "lon", "category"}
    for position, record in enumerate(records, 1):
        missing = required - record.keys()
        if missing:
            raise ValueError(f"record {position} missing {sorted(missing)}")
        if record["category"] not in CATEGORY_JA:
            raise ValueError(f"record {position} has unknown category {record['category']}")
    if len({record["id"] for record in records}) != len(records):
        raise ValueError("duplicate brewery IDs")
    return records, overlay


def slugify(record: dict) -> str:
    normalized = unicodedata.normalize("NFKD", record["name"]).encode("ascii", "ignore").decode().lower()
    name = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-") or "facility"
    return f'{record["id"]}-{name}'


def category_label(record: dict, english: bool) -> str:
    return (CATEGORY_EN if english else CATEGORY_JA)[record["category"]]


def prefecture(record: dict, english: bool) -> str:
    value = record.get("pref") or ""
    return PREF_EN.get(value, value) if english else value


def qualifier(record: dict, english: bool, duplicate_names: set[str]) -> str:
    location = prefecture(record, english)
    if record["name"] in duplicate_names and not location:
        location = f'{record["lat"]:.4f}, {record["lon"]:.4f}'
    parts = [part for part in (location, category_label(record, english)) if part]
    return " · ".join(parts)


def subject(record: dict, english: bool, duplicate_names: set[str]) -> str:
    return f'{record["name"]} — {qualifier(record, english, duplicate_names)}'


def brand_name(record: dict, english: bool, overlay: dict[str, dict]) -> str:
    if english:
        return overlay.get(str(record["id"]), {}).get("brand") or record.get("brand") or ""
    return record.get("brand") or ""


def meta_description(record: dict, english: bool, duplicate_names: set[str], overlay: dict[str, dict]) -> str:
    cat = category_label(record, english)
    pref = prefecture(record, english)
    place = pref or ("Japan" if english else "日本")
    brand = brand_name(record, english, overlay)
    if english:
        text = f'{record["name"]} is listed as a {cat.lower()} in {place}. View its address, map coordinates, website, and award record.'
        if brand:
            text = f'{record["name"]}, a {cat.lower()} in {place}. Brand: {brand}. View address, coordinates, website, and award record.'
    else:
        text = f'{record["name"]}は{place}の{cat}として掲載されています。住所、地図座標、ウェブサイト、受賞記録を確認できます。'
        if brand:
            text = f'{record["name"]}（{place}・{cat}）。代表銘柄は{brand}。住所、地図座標、ウェブサイト、受賞記録を確認できます。'
    if record["name"] in duplicate_names and not record.get("pref"):
        text += f' ({record["lat"]:.4f}, {record["lon"]:.4f})'
    return text if len(text) <= 155 else text[:154].rstrip() + "…"


def fact(label: str, value: object) -> str:
    return f"<div><dt>{esc(label)}</dt><dd>{esc(value)}</dd></div>"


def award_facts(record: dict, english: bool) -> str:
    award = record.get("award")
    if not award:
        return ""
    competition = (COMPETITION_EN if english else COMPETITION_JA).get(record["category"], "Award" if english else "受賞歴")
    years = ", ".join(str(year) for year in award.get("years", []))
    gold = ", ".join(str(year) for year in award.get("gold_years", []))
    result = fact("Competition" if english else "受賞対象", competition)
    if years:
        result += fact("Award years" if english else "入賞年", years)
    if gold:
        result += fact("Gold award years" if english else "金賞年", gold)
    return result


def related_indices(records: list[dict]) -> list[list[int]]:
    result = []
    for i, item in enumerate(records):
        ranked = sorted(
            (j for j in range(len(records)) if j != i),
            key=lambda j: (
                -(bool(item.get("pref")) and records[j].get("pref") == item.get("pref")),
                -(records[j]["category"] == item["category"]),
                (records[j]["lat"] - item["lat"]) ** 2 + (records[j]["lon"] - item["lon"]) ** 2,
                records[j]["name"], records[j]["id"],
            ),
        )
        result.append(ranked[:6])
    return result


def schema(record: dict, slug: str, english: bool, duplicate_names: set[str], overlay: dict[str, dict]) -> str:
    lang = "en" if english else "ja"
    prefix = "en/" if english else ""
    canonical = f"{BASE}/{prefix}items/{slug}/"
    entity_id = f"{canonical}#facility"
    entity_type = "Winery" if record["category"] == "wine" else "Brewery" if record["category"] in {"sake", "beer"} else "Organization"
    location = {"@type": "Place", "geo": {"@type": "GeoCoordinates", "latitude": record["lat"], "longitude": record["lon"]}}
    if record.get("address"):
        location["address"] = {"@type": "PostalAddress", "streetAddress": record["address"], "addressCountry": "JP"}
    entity = {"@type": entity_type, "@id": entity_id, "name": record["name"], "url": canonical}
    if entity_type == "Organization":
        entity["location"] = location
    else:
        entity["geo"] = location["geo"]
        if location.get("address"):
            entity["address"] = location["address"]
    brand = brand_name(record, english, overlay)
    if brand:
        entity["brand"] = {"@type": "Brand", "name": brand}
    same_as = [url for url in (record.get("website"), record.get("wikipedia")) if url]
    if same_as:
        entity["sameAs"] = same_as
    if record.get("award"):
        competition = (COMPETITION_EN if english else COMPETITION_JA).get(record["category"], "Award" if english else "受賞歴")
        entity["award"] = [f"{competition} ({year})" for year in record["award"].get("years", [])]
    graph = [
        {"@type": "WebSite", "@id": f"{BASE}/#website", "url": f"{BASE}/", "name": "Japan Sake Brewery Map" if english else "全国酒蔵マップ", "inLanguage": ["ja", "en"]},
        {"@type": "WebPage", "@id": f"{canonical}#webpage", "url": canonical, "name": subject(record, english, duplicate_names), "inLanguage": lang, "isPartOf": {"@id": f"{BASE}/#website"}, "mainEntity": {"@id": entity_id}},
        entity,
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home" if english else "トップ", "item": f"{BASE}/{prefix}"},
            {"@type": "ListItem", "position": 2, "name": "Facility index" if english else "醸造施設索引", "item": f"{BASE}/{prefix}items/"},
            {"@type": "ListItem", "position": 3, "name": subject(record, english, duplicate_names), "item": canonical},
        ]},
    ]
    return json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def detail_context(record: dict, slug: str, related: list[int], records: list[dict], slugs: list[str], overlay: dict[str, dict], english: bool, duplicate_names: set[str]) -> dict[str, str]:
    cat = category_label(record, english)
    title = subject(record, english, duplicate_names)
    labels = ("Type", "Prefecture", "Address", "Coordinates", "Brand") if english else ("種別", "都道府県", "住所", "地図座標", "代表銘柄")
    facts = fact(labels[0], cat)
    values = [prefecture(record, english), record.get("address"), f'{record["lat"]}, {record["lon"]}', brand_name(record, english, overlay)]
    for label_text, value in zip(labels[1:], values):
        if value:
            facts += fact(label_text, value)
    facts += award_facts(record, english)
    links = "".join(f'<li><a href="../{slugs[i]}/">{esc(subject(records[i], english, duplicate_names))}</a></li>' for i in related)
    external = []
    if record.get("website"):
        external.append(f'<a class="secondary-action" href="{esc(record["website"])}" target="_blank" rel="noopener noreferrer">{"Website" if english else "ウェブサイト"}</a>')
    if record.get("wikipedia"):
        external.append(f'<a class="secondary-action" href="{esc(record["wikipedia"])}" target="_blank" rel="noopener noreferrer">Wikipedia</a>')
    prefix = "en/" if english else ""
    app_root = "../../../" if english else "../../"
    app_url = f'{app_root}{"en/" if english else ""}?id={record["id"]}'
    maps_url = f'https://www.openstreetmap.org/?mlat={record["lat"]}&mlon={record["lon"]}#map=16/{record["lat"]}/{record["lon"]}'
    return {
        "slug": slug, "title": esc(title), "page_title": esc(f'{title} | {"Japan Brewery Map" if english else "全国酒蔵マップ"}'),
        "meta_description": esc(meta_description(record, english, duplicate_names, overlay)), "canonical": f"{BASE}/{prefix}items/{slug}/",
        "ja_url": f"{BASE}/items/{slug}/", "en_url": f"{BASE}/en/items/{slug}/", "og_image": OG_IMAGE,
        "json_ld": schema(record, slug, english, duplicate_names, overlay), "category": esc(cat), "facts": facts, "app_url": app_url,
        "maps_url": esc(maps_url), "external_links": "".join(external), "related": links,
    }


def index_groups(records: list[dict], slugs: list[str], english: bool, duplicate_names: set[str]) -> str:
    grouped: dict[str, dict[str, list[tuple[str, str]]]] = defaultdict(lambda: defaultdict(list))
    for record, slug in zip(records, slugs):
        category = category_label(record, english)
        area = prefecture(record, english) or ("Prefecture unavailable" if english else "都道府県情報なし")
        grouped[category][area].append((record["name"], slug))
    sections = []
    for category in (CATEGORY_EN.values() if english else CATEGORY_JA.values()):
        if category not in grouped:
            continue
        areas = []
        for area in sorted(grouped[category]):
            links = "".join(f'<li><a href="{slug}/">{esc(name)}</a></li>' for name, slug in sorted(grouped[category][area], key=lambda x: (x[0], x[1])))
            areas.append(f'<section class="area-group"><h3>{esc(area)}</h3><ul>{links}</ul></section>')
        sections.append(f'<section class="category-group"><h2>{esc(category)}</h2>{"".join(areas)}</section>')
    return "".join(sections)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def main() -> None:
    records, overlay = load_data()
    duplicate_names = {name for name, count in Counter(record["name"] for record in records).items() if count > 1}
    slugs = [slugify(record) for record in records]
    if len(slugs) != len(set(slugs)):
        raise ValueError("duplicate slugs")
    related = related_indices(records)
    templates = {name: Template((ROOT / f"templates/{name}.html").read_text(encoding="utf-8")) for name in ("detail_ja", "detail_en", "index_ja", "index_en")}
    for directory in (ROOT / "items", ROOT / "en/items"):
        if directory.exists():
            shutil.rmtree(directory)
    for i, (record, slug) in enumerate(zip(records, slugs)):
        write(ROOT / "items" / slug / "index.html", templates["detail_ja"].substitute(detail_context(record, slug, related[i], records, slugs, overlay, False, duplicate_names)))
        write(ROOT / "en/items" / slug / "index.html", templates["detail_en"].substitute(detail_context(record, slug, related[i], records, slugs, overlay, True, duplicate_names)))
    common = {"count": f"{len(records):,}", "ja_url": f"{BASE}/items/", "en_url": f"{BASE}/en/items/"}
    write(ROOT / "items/index.html", templates["index_ja"].substitute(common, groups=index_groups(records, slugs, False, duplicate_names)))
    write(ROOT / "en/items/index.html", templates["index_en"].substitute(common, groups=index_groups(records, slugs, True, duplicate_names)))
    urls = [f"{BASE}/", f"{BASE}/en/", f"{BASE}/about.html", f"{BASE}/en/about.html", f"{BASE}/privacy.html", f"{BASE}/en/privacy.html", f"{BASE}/items/", f"{BASE}/en/items/"]
    urls += [f"{BASE}/items/{slug}/" for slug in slugs] + [f"{BASE}/en/items/{slug}/" for slug in slugs]
    sitemap = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "".join(f"  <url><loc>{esc(url)}</loc></url>\n" for url in urls) + "</urlset>\n"
    write(ROOT / "sitemap.xml", sitemap)
    write(ROOT / "robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {BASE}/sitemap.xml\n")
    print(f"Generated {len(records) * 2:,} detail pages, 2 indexes, and {len(urls):,} sitemap URLs.")


if __name__ == "__main__":
    main()
