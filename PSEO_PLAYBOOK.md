# 醸造施設データ向けプログラマティックSEO運用手順

`sake-brewery-map` の施設データから、日英の事実情報ページを再生成・検証するための手順書です。

## 構成

- `scripts/generate_pages.py`: 施設詳細、索引、sitemap、robotsを一括生成
- `scripts/validate_generated_pages.py`: 件数、SEO要素、JSON-LD、内部リンク、説明文除外、OSM帰属表示を検証
- `templates/detail_ja.html` / `templates/detail_en.html`: 日英詳細テンプレート
- `templates/index_ja.html` / `templates/index_en.html`: 日英索引テンプレート
- `items/<id-name>/index.html` / `en/items/<id-name>/index.html`: 生成物
- `sitemap.xml` / `robots.txt`

## 入力とURL

`breweries.json` の3,307件を入力とする。IDをslugの先頭に含め、施設名の表記変更や同名施設があっても一意になるようにする。

- 日本語: `/items/<id-name>/`
- 英語: `/en/items/<id-name>/`

英語施設名・英語住所は推測しない。施設名は原表記、都道府県は既存の英語対応表、住所は日本語フォールバックを使う。英語銘柄名は `data/featured-en.json` に存在する場合だけ使用する。

## 出力可能な事実情報

- 施設名、種別、都道府県、住所
- 緯度・経度（近似値を含む旨を併記）
- 代表銘柄名
- 受賞対象、入賞年、金賞年
- 公式サイト、Wikipedia、地図リンク

`desc` と `data/featured-en.json` の `desc` は、本文、title、meta description、OGP、JSON-LD、索引のすべてから除外する。外部サイトの紹介文、画像、営業時間、見学可否も取得・推測しない。

## schema.org

- 清酒・地ビール: `Brewery`
- ワイン: `Winery`
- 焼酎・泡盛: `Organization` と `location: Place`
- 全ページ: `WebPage`、`WebSite`、`BreadcrumbList`

座標は `GeoCoordinates`、住所は値がある場合だけ `PostalAddress` に入れる。公式サイトとWikipediaは `sameAs`、受賞年はコンテスト名付きの `award` とする。営業時間、電話番号、営業形態など、データにない値は入れない。

## データ出所と帰属

施設・位置データにはOpenStreetMap由来情報が含まれるため、詳細ページと索引の両方に `© OpenStreetMap contributors` とODbLへのリンクを常時表示する。座標にはNominatimで住所から算出した近似位置もあるため、施設ピンポイントとは限らない旨も表示する。

情報は複数の公開情報源を統合したデータ提供時点の内容であり、版や更新時期によって変わり得ることを日英で明記する。

## AdSense・英語構造・地図導線

既存の `config.js` と `ads.js` を相対パスで読み込み、本番ホストだけで既存publisher IDを読み込む条件を維持する。canonicalと `ja` / `en` / `x-default` hreflangを相互設定する。

詳細ページの「地図アプリで表示」は `?id=<施設ID>` を使用する。`js/app.js` は初回読込時だけ該当マーカーへ移動し、ポップアップを開く。通常の地図利用、検索、絞り込みは変更しない。

## sitemapとService Worker

3,307件×2言語、索引2ページ、既存主要6ページを単一sitemapに収録する。生成ページはService Workerの事前キャッシュ一覧へ追加しない。閲覧時取得とし、数千ページを一括保存しない。

## 更新・検証

```sh
python3 scripts/generate_pages.py
python3 scripts/validate_generated_pages.py
git diff --check
```

生成物は手編集しない。修正は入力JSON、テンプレート、生成スクリプトへ行う。同じ入力から再生成した際にハッシュが一致することを確認する。

## 公開前チェック

- [ ] 日英それぞれ3,307ページ
- [ ] slugとIDが一意で日英一致
- [ ] title、meta description、canonical、hreflangが各ページに存在
- [ ] JSON-LDが構文エラーなく事実情報だけを含む
- [ ] `desc` が全生成物に存在しない
- [ ] OSM帰属・ODbLリンクが詳細と索引にある
- [ ] 内部リンク切れがない
- [ ] sitemapが6,622 URLで重複なし
- [ ] 生成ページが事前キャッシュ対象外
- [ ] 地図への `?id=` リンクが該当施設を開く
- [ ] モバイル幅とデスクトップ幅で代表ページを目視確認
- [ ] `.wrangler/` をコミット対象に含めない
- [ ] git push前にオーナー承認を得る
