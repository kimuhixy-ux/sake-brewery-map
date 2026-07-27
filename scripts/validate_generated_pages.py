#!/usr/bin/env python3
"""Validate generated facility pages and fact-only output rules."""

from __future__ import annotations

import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = 3307


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def validate_links(path: Path, text: str) -> None:
    for href in re.findall(r'href="([^"]+)"', text):
        parsed = urlsplit(href.replace("&amp;", "&"))
        if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.startswith("/"):
            continue
        target = (path.parent / unquote(parsed.path)).resolve()
        if target.is_dir():
            target /= "index.html"
        if not target.exists():
            fail(f"{path.relative_to(ROOT)} broken link: {href}")


def main() -> None:
    records = json.loads((ROOT / "breweries.json").read_text(encoding="utf-8"))
    excluded = {record["desc"] for record in records if record.get("desc")}
    overlay = json.loads((ROOT / "data/featured-en.json").read_text(encoding="utf-8"))
    excluded.update(value["desc"] for value in overlay.values() if value.get("desc"))
    ja = sorted((ROOT / "items").glob("*/index.html"))
    en = sorted((ROOT / "en/items").glob("*/index.html"))
    if len(ja) != EXPECTED or len(en) != EXPECTED:
        fail(f"page count ja={len(ja)} en={len(en)}")
    if [path.parent.name for path in ja] != [path.parent.name for path in en]:
        fail("locale slug sets differ")

    required = ['rel="canonical"', 'hreflang="ja"', 'hreflang="en"', 'hreflang="x-default"', '"@type":"WebPage"', '"@type":"BreadcrumbList"', 'name="twitter:card" content="summary_large_image"', 'config.js', 'ads.js', 'OpenStreetMap contributors', 'ODbL']
    entity_counts = {"Brewery": 0, "Winery": 0, "Organization": 0}
    for language, pages in (("ja", ja), ("en", en)):
        titles: set[str] = set()
        descriptions: set[str] = set()
        for path in pages:
            text = path.read_text(encoding="utf-8")
            missing = [value for value in required if value not in text]
            if missing:
                fail(f"{path.relative_to(ROOT)} missing {missing}")
            if any(value in text for value in excluded):
                fail(f"{path.relative_to(ROOT)} reproduces an excluded description")
            title_match = re.search(r"<title>(.*?)</title>", text, re.S)
            meta_match = re.search(r'<meta name="description" content="([^"]*)">', text)
            if not title_match or not meta_match:
                fail(f"{path.relative_to(ROOT)} lacks title or meta description")
            title = html.unescape(title_match.group(1))
            description = html.unescape(meta_match.group(1))
            if title in titles or description in descriptions:
                fail(f"{path.relative_to(ROOT)} has duplicate title or meta description")
            if len(description) > 155:
                fail(f"{path.relative_to(ROOT)} meta description exceeds 155 characters")
            titles.add(title)
            descriptions.add(description)
            match = re.search(r'<script type="application/ld\+json">(.*?)</script>', text, re.S)
            try:
                structured = json.loads(match.group(1) if match else "")
            except json.JSONDecodeError as exc:
                fail(f"{path.relative_to(ROOT)} invalid JSON-LD: {exc}")
            serialized = json.dumps(structured, ensure_ascii=False)
            for entity_type in entity_counts:
                entity_counts[entity_type] += f'"@type": "{entity_type}"' in serialized
            validate_links(path, text)

    expected_types = {"Brewery": (1590 + 1051) * 2, "Winery": 405 * 2, "Organization": (222 + 39) * 2}
    if entity_counts != expected_types:
        fail(f"schema entity counts {entity_counts}, expected {expected_types}")

    for path in (ROOT / "items/index.html", ROOT / "en/items/index.html"):
        text = path.read_text(encoding="utf-8")
        if text.count('<li><a href="') != EXPECTED:
            fail(f"{path.relative_to(ROOT)} index count mismatch")
        if any(value in text for value in excluded):
            fail(f"{path.relative_to(ROOT)} reproduces an excluded description")
        if "OpenStreetMap contributors" not in text or "ODbL" not in text:
            fail(f"{path.relative_to(ROOT)} lacks OSM attribution")
        validate_links(path, text)

    root = ET.parse(ROOT / "sitemap.xml").getroot()
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [node.text for node in root.findall("s:url/s:loc", ns)]
    if len(urls) != EXPECTED * 2 + 8 or len(urls) != len(set(urls)):
        fail(f"invalid sitemap URL set: {len(urls)}")
    if "https://kimuhixy.com/sake-brewery-map/sitemap.xml" not in (ROOT / "robots.txt").read_text(encoding="utf-8"):
        fail("robots.txt sitemap missing")
    if '.get("id")' not in (ROOT / "js/app.js").read_text(encoding="utf-8"):
        fail("map app lacks generated-page deep-link handling")
    print(f"Validated {len(ja) + len(en):,} fact-only detail pages, 2 indexes, and {len(urls):,} sitemap URLs.")


if __name__ == "__main__":
    main()
