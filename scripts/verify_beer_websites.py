#!/usr/bin/env python3
"""beer_list_geocoded.jsonの各醸造所に付いているwebsite URLへ実際に
アクセスして疎通確認し、繋がらないもの(削除・移転済み、またはPDFの
表組みが横幅の都合で途中で切れて壊れたURLになっているもの)をNoneに
落とす。

北山産業のPDF(scripts/scrape_beer_list.py参照)は表が横に長くなる行だと
「ホームページ」列のURLが途中で切れて出力されることがあり、その場合
リンクを貼っても404やDNSエラーになるため、事前に検証しておく。

結果はURLごとにcontact_verify_cache.jsonにキャッシュし、再実行時は
新規URLのみ確認する(全件チェックを毎回やり直さない)。

標準ライブラリのみで書かれているので、pip installは不要。
使い方: python3 scripts/verify_beer_websites.py
"""

import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_PATH = BASE_DIR / "beer_list_geocoded.json"
OUTPUT_PATH = BASE_DIR / "beer_list_geocoded.json"
CACHE_PATH = BASE_DIR / "beer_list_website_verify_cache.json"

# facebook/instagram/x(twitter)はログイン壁や存在しないパスでもSPAが
# 200を返すため、HTTPステータスによる疎通確認が機能しない(実際に
# 存在しないパスへ疎通確認しても常にOK判定になってしまう)。
# 「公式サイト」ボタンの意味的にもSNSアカウントは想定していないため、
# これらのドメインは疎通確認の対象にせず、website欄からは除外する。
SOCIAL_DOMAIN_RE = re.compile(
    r"^https?://(www\.)?(facebook\.com|instagram\.com|twitter\.com|x\.com)", re.IGNORECASE
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; sake-brewery-map/1.0; "
    "+https://github.com/kimuhixy-ux/sake-brewery-map)"
}
TIMEOUT_SECONDS = 8
REQUEST_DELAY_SECONDS = 0.3

# 証明書切れ・自己署名証明書のURLも「サイト自体は実在する」とみなして
# 有効扱いにする(SSLエラーだけでリンクを消すと、正規サイトでも証明書が
# 一時的に古いだけのケースまで落としてしまうため)。
SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE


def encode_url(url):
    """パス・クエリに含まれる非ASCII文字(日本語のFacebookページ名など)を
    パーセントエンコードする。urlopen()はlatin-1で送出するヘッダーしか
    扱えず、非ASCII文字を含むURLをそのまま渡すとUnicodeEncodeErrorになる。
    """
    parts = urllib.parse.urlsplit(url)
    try:
        netloc = parts.netloc.encode("ascii").decode("ascii")
    except UnicodeEncodeError:
        netloc = parts.netloc.encode("idna").decode("ascii")
    path = urllib.parse.quote(parts.path, safe="/%")
    query = urllib.parse.quote(parts.query, safe="=&%")
    fragment = urllib.parse.quote(parts.fragment, safe="%")
    return urllib.parse.urlunsplit((parts.scheme, netloc, path, query, fragment))


def check_url(url):
    """疎通確認する。生きていればTrue。"""
    url = encode_url(url)
    req = urllib.request.Request(url, headers=HEADERS, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS, context=SSL_CONTEXT) as resp:
            return resp.status < 400
    except urllib.error.HTTPError as e:
        # HEADを許可していないサーバーがそれなりにあるため、405/501等はGETで再試行する。
        if e.code in (405, 501):
            pass
        elif e.code < 500:
            # 403等でも実在するサイトであることは多い(bot対策でHEADを拒否)。
            return True
        else:
            return False
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return False

    req = urllib.request.Request(url, headers=HEADERS, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS, context=SSL_CONTEXT) as resp:
            return resp.status < 400
    except urllib.error.HTTPError as e:
        return e.code < 400
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return False


def main():
    with open(INPUT_PATH, encoding="utf-8") as f:
        entries = json.load(f)

    social_dropped = 0
    for e in entries:
        if e.get("website") and SOCIAL_DOMAIN_RE.match(e["website"]):
            e["website"] = None
            social_dropped += 1
    print(f"SNSドメイン(疎通確認が機能しないため対象外): {social_dropped}件")

    cache = {}
    if CACHE_PATH.exists():
        with open(CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)
        print(f"キャッシュを読み込みました({len(cache)}件)。")

    urls = sorted({e["website"] for e in entries if e.get("website")})
    print(f"確認対象URL: {len(urls)}件")

    checked = 0
    for i, url in enumerate(urls, 1):
        if url in cache:
            continue
        try:
            ok = check_url(url)
        except Exception as e:
            print(f"  確認エラー({url}): {e}")
            ok = False
        cache[url] = ok
        checked += 1
        print(f"[{i}/{len(urls)}] {'OK' if ok else 'NG'} {url}")
        time.sleep(REQUEST_DELAY_SECONDS)
        if checked % 20 == 0:
            with open(CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)

    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    dropped = 0
    for e in entries:
        url = e.get("website")
        if url and not cache.get(url, False):
            e["website"] = None
            dropped += 1

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    alive = sum(1 for e in entries if e.get("website"))
    print()
    print(f"疎通NGにより除外: {dropped}件")
    print(f"最終的に有効なURL: {alive}件 / {len(entries)}件")
    print(f"出力先: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
