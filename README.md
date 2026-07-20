# sake-brewery-map（全国酒蔵マップ）

全国の酒蔵をOpenStreetMapのデータで1枚の地図にプロットするPWA。サーバー不要の静的サイトで、ビルドツールも使わない。有名な酒蔵・銘柄には解説を表示する。

## 使い方（iPhoneでホーム画面に追加）

1. iPhoneのSafariで公開URL（GitHub Pagesのアドレス）を開く
2. 地図が表示されたら共有ボタン（□に↑）をタップ
3. 「ホーム画面に追加」を選択

これでアイコンをタップするだけで単独アプリのように起動する。

## 機能

- Leaflet.js + OpenStreetMapタイルによる地図表示、マーカーはクラスタリング対応
- 銘柄解説がある蔵は金色ピン、それ以外は藍色ピンで区別（色はfeatured状態）
- 清酒の蔵は丸、焼酎の蔵はひし形のマーカーで区別（形はcategory）
- 蔵名・銘柄名で検索、都道府県で絞り込み、種別（清酒/焼酎）で絞り込み、「銘柄解説のある蔵のみ」トグル
- ポップアップに蔵名・種別バッジ・代表銘柄・特徴解説・住所・「マップで開く」「経路」（Apple純正マップに連携）・公式サイト/Wikipediaへのリンクを表示
- 現在地ボタン
- PWA対応（ホーム画面に追加してオフラインでも地図UI自体は起動可能。地図タイル自体はオンラインが必要）

## データの更新方法

酒蔵の位置データは**OpenStreetMap（Overpass API）**と、**日本酒造組合中央会「酒蔵検索」のマスターリスト**を組み合わせて取得した静的JSON（`breweries.json`）。実行時にAPIを呼び出さない設計のため、最新化するには以下を実行する。

```bash
python3 fetch_breweries.py
```

- 標準ライブラリのみ（`urllib`）で書かれているため、pip installは不要。
- Overpass APIには負荷制限があるため、エンドポイントを2つ用意し、失敗時は待機してリトライ、それでもダメなら別エンドポイントに切り替える（最大で数分かかることがある）。
- `craft=sake_brewery`タグはOSM上でほとんど使われていないため、それとは別に「タグの種類を問わず、名称に酒造・酒蔵・銘醸を含む施設」を全国から検索する方式にしている（名称インデックスを使うため、この方式でないとOverpass側のタイムアウトに掛かりやすい）。
- 居酒屋・飲食店（`amenity=restaurant`等）や、「住宅公園」「ハウジング」「ドライブイン」といった、名称に酒造/酒蔵を含むだけの無関係な施設は除外している。
- 同じ蔵が複数のタグ種別（`craft`/`shop`/`landuse`/`building`など）で重複して登録されていることがあるため、正規化した名称が同じで座標も近い（約1km以内）ものは1件にまとめている。
- OSMはクラウドソースであるため、観光客向けの店舗を持たない小規模な蔵元が登録されていないことが多い。これを補うため、`master_list_geocoded.json`（下記「マスターリストの更新方法」参照）にある清酒・焼酎蔵元のうち、OSM側に未登録（正規化名+都道府県が一致しない、かつ`sake_info.json`経由でも同一エントリにマッチしない）のものを追加している。マスターリスト由来のレコードは住所をNominatimでジオコーディングした近似座標（市区町村〜字レベルのことが多く、施設ピンポイントの精度ではない）で、`website`・`wikipedia`は付与されない。
- 各レコードは`category`（`"sake"`または`"shochu"`）を持つ。マスターリスト由来のレコードはサイト側の分類をそのまま使う。OSM由来のレコードはOSM自体が清酒/焼酎を区別しないためデフォルトで`"sake"`扱いだが、マスターリストの焼酎蔵と同一蔵だと判定された場合は`"shochu"`に上書きされる。
- `sake_info.json`（下記）と名称・都道府県で突き合わせ、一致した蔵には`featured: true`と銘柄名・解説が付く。
- 実行結果は標準出力に「取得件数」「マスターリストから追加した件数」「銘柄情報がマッチした件数」が表示される。
- OSMにもマスターリストにも登録がなく通常の検索では拾えない蔵（例: 清酒以外を主とする蔵など）は、`fetch_breweries.py`内の`MANUAL_ENTRIES`に座標（住所から調べた地区レベルの概算）を手動で追加することで地図に表示できる。`breweries.json`を直接編集しても次回実行時に上書きされるため、追加は必ず`MANUAL_ENTRIES`側で行うこと。

## マスターリストの更新方法

日本酒造組合中央会「酒蔵検索」（https://japansake.or.jp/sakagura/jp/）を情報源とする全国清酒蔵元リスト。robots.txtにクロール制限は無く、明確な再利用禁止の記載も無いことを確認済み。蔵名・住所・カテゴリ（清酒/焼酎）といった事実情報のみを抽出し、解説文などの著作物はそのまま複製しない方針にしている。

```bash
python3 scripts/scrape_master_list.py    # 全47都道府県をスクレイピングし、master_list_raw.jsonを生成
python3 scripts/geocode_master_list.py   # 住所をNominatimでジオコーディングし、master_list_geocoded.jsonを生成
```

- どちらも標準ライブラリのみで書かれているため、pip installは不要。
- `scrape_master_list.py`は清酒（`class="sake"`）・焼酎（`class="shochu"`）の両方を対象にし、サイト側の分類をそのまま`category`として保存する。
- `geocode_master_list.py`はNominatimの利用ポリシーに従い1秒に1リクエストのレート制限をかけているため、1,500件規模だと1時間前後かかる。番地まで含めた住所でヒットしない場合は末尾を段階的に削って町・字レベルまでフォールバックする。また、日本語住所は都道府県・郡・市区町村などの行政区画の境目にスペースを入れないとNominatim側でヒットしないことが多いため、区切りにスペースを挿入した候補を優先的に試す。
- 結果は`master_list_geocode_cache.json`に住所文字列をキーにしてキャッシュされるため、途中で中断しても再実行時に再ジオコーディングをスキップできる。

## sake_info.jsonの編集方法

有名な酒蔵・銘柄の解説データ。以下の形式でエントリを追加・編集する。

```json
{
  "brewery": "旭酒造",
  "pref": "山口県",
  "brand": "獺祭",
  "desc": "岩国市の蔵。純米大吟醸のみを醸す蔵で、山田錦を高精白し、華やかな香りときれいな甘みで世界的な知名度を持つ。"
}
```

- `brewery`はOSM上の蔵名と一致（会社形態の表記ゆれは自動で吸収されるので「株式会社」の有無は気にしなくてよい）。同名の蔵が複数県にある場合は`pref`で区別するため、必ず正確な都道府県名を入れる。
- `desc`は確実な事実のみを書く（受賞歴や生産量など、うろ覚えの数値は書かない）。
- 編集したら`python3 fetch_breweries.py`を再実行して`breweries.json`に反映する。

## GitHub Pagesでの公開手順

```bash
cd ~/sake-brewery-map
git init
git add .
git commit -m "Initial commit"
gh repo create kimuhixy-ux/sake-brewery-map --public --source=. --push
```

その後、GitHubリポジトリの Settings → Pages で、Source を「Deploy from a branch」、Branch を `main` / `(root)` に設定すると、`https://kimuhixy-ux.github.io/sake-brewery-map/` で公開される（反映まで数分かかることがある）。

データを更新した場合は、`python3 fetch_breweries.py`を実行後、変更を commit & push すれば反映される。

## データ出典・注意事項

- データ出典はOpenStreetMapと日本酒造組合中央会「酒蔵検索」。網羅性は地域によって差がある。
- OSM検索範囲を広げるため、`craft`タグに限らずタグの種類を問わず名称一致で検索している。そのため、まれに酒蔵とは無関係な施設（同じ名称を含む店舗など）が紛れ込む可能性がある（気づいた場合は`fetch_breweries.py`の`NOISE_NAME_KEYWORDS`に除外キーワードを追加する）。
- 都道府県（`pref`）はOSM側は`addr:province`等のタグがある場合のみ、マスターリスト側は住所から常に入る。無い場合は`null`となり、都道府県での絞り込みには出てこない。
- マスターリスト由来のレコードは座標がNominatimによる住所検索の近似値であり、施設ピンポイントの精度ではない（地図上でズレていることがある）。
- OSMのブランド名のみの登録（例:「真澄」）とマスターリストの正式社名登録（例:「宮坂醸造」）が`sake_info.json`経由で同一エントリにマッチする場合は1件に統合しているが、`sake_info.json`に載っていない蔵で、かつOSMとマスターリストで名称の字体が大きく異なる（異体字など）場合は、ごくまれに同じ蔵が2件のピンとして重複表示されることがある。
- 地図の帰属表示（OpenStreetMap contributors）は必ず残すこと。

## ファイル構成

```
sake-brewery-map/
├── index.html
├── css/style.css
├── js/app.js
├── breweries.json
├── sake_info.json
├── fetch_breweries.py
├── master_list_raw.json
├── master_list_geocoded.json
├── master_list_geocode_cache.json
├── manifest.json
├── sw.js
├── icons/
│   ├── icon-192.png
│   ├── icon-512.png
│   └── apple-touch-icon.png
├── scripts/
│   ├── generate_icons.py
│   ├── scrape_master_list.py
│   └── geocode_master_list.py
└── vendor/
    ├── leaflet/（leaflet.js, leaflet.css, images/）
    └── markercluster/（leaflet.markercluster.js, MarkerCluster*.css）
```
