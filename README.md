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
- 清酒の蔵は丸、焼酎の蔵はひし形、泡盛の蔵は三角形、地ビールの醸造所は四角形、ワイナリーは六角形のマーカーで区別（形はcategory）
- 蔵名・銘柄名で検索、都道府県で絞り込み、種別（清酒/焼酎/泡盛/地ビール/ワイン）で絞り込み、「銘柄解説のある蔵のみ」「受賞歴のある蔵のみ」トグル
- ポップアップに蔵名・種別バッジ・代表銘柄・特徴解説・全国新酒鑑評会の入賞歴（清酒のみ）・住所・「マップで開く」「経路」（Apple純正マップに連携）・公式サイト/Wikipediaへのリンクを表示
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
  - 都道府県が分からないOSMレコードは正規化名のみでマスターリストと突き合わせるが、「田中酒造」「上原酒造」のように同名で無関係な蔵が別々の県に実在するケースがあるため、この経路だけは両者の座標が100km以内の場合に限って同一視する（近似ジオコーディングの誤差は許容しつつ、遠く離れた同名の別蔵を誤って統合・除外しないようにするため）。
- 各レコードは`category`（`"sake"`・`"shochu"`・`"awamori"`のいずれか）を持つ。マスターリスト由来のレコードはサイト側の分類（清酒/焼酎の2種類）をそのまま使うが、酒税法上泡盛は焼酎の一種であり、かつ地理的表示保護により沖縄県産のみのため、`category="shochu"`かつ住所が沖縄県のものは`"awamori"`に読み替える。OSM由来のレコードはOSM自体がこれらを区別しないためデフォルトで`"sake"`扱いだが、マスターリスト側で焼酎/泡盛と判定された同一蔵だと分かった場合はその`category`で上書きされる。
- `sake_info.json`（下記）と名称・都道府県で突き合わせ、一致した蔵には`featured: true`と銘柄名・解説が付く。
- 実行結果は標準出力に「取得件数」「マスターリストから追加した件数」「銘柄情報がマッチした件数」が表示される。
- OSMにもマスターリストにも登録がなく通常の検索では拾えない蔵（例: 清酒以外を主とする蔵など）は、`fetch_breweries.py`内の`MANUAL_ENTRIES`に座標（住所から調べた地区レベルの概算）を手動で追加することで地図に表示できる。`breweries.json`を直接編集しても次回実行時に上書きされるため、追加は必ず`MANUAL_ENTRIES`側で行うこと。

## 地ビール(クラフトビール)データについて

種別に「地ビール」を追加している。酒蔵と同様、**OSM(Overpass API)**と、**北山産業(Kita Sangyo Co., Ltd)が公開する全国クラフトビール醸造所リスト**を組み合わせて取得している。`fetch_breweries.py`実行時に自動で統合され、`breweries.json`に`category="beer"`として保存される。

- OSM側は`craft=brewery`・`microbrewery=yes`のタグが付いた地物のみを検索範囲とし、その中で名称にビール関連語を含む、または`product`タグに`beer`を含むものだけを採用する(酒蔵名(酒造/酒蔵/銘醸)を含む場合は、`product=beer`で明示されない限り酒蔵側とみなして除外する)。名称の全国検索(酒蔵側のNAME_PATTERNに相当する方式)は行わない。「ビール」「ホップ」等ビールに関連する語は、バス停名(「アサヒビール」等の工場前バス停)や無関係な語("ベビールーム"に「ビール」が部分文字列として含まれる、「ショップ」に「hop」が含まれる等)との衝突が非常に多く、全国検索すると数百〜数千件のノイズを拾ってしまうことが実データ確認で分かったため。
- OSM単独では全国で80件前後(craft=breweryタグの登録状況に依存)しか拾えず、業界推定(全国950箇所以上)に遠く及ばないため、下記「地ビールマスターリストの更新方法」のリストで補っている。マスターリスト由来のレコードは住所をNominatimでジオコーディングした近似座標で、`website`・`wikipedia`は付与されない。
- 統合の突合ロジックは酒蔵のマスターリストと同じ(正規化名+都道府県が一致、または都道府県が無い場合は正規化名+座標が100km以内)だが、`sake_info.json`のような銘柄解説データとの突合は行わない。
- 銘柄解説(金色ピン)の仕組みは今のところ地ビールには適用していない(全件が通常ピンで表示される)。

## 地ビールマスターリストの更新方法

北山産業が公開しているクラフトビール醸造所リスト(https://kitasangyo.com/beer/MAP.html )を情報源とする。地域別10リストに加え、地域別リストの一部(北海道・北陸・近畿・中国・四国・信越)が2021年12月末時点のまま更新されていないのを補うため、年別(2022〜2025年)の全国新規開業リストも合わせて使う。robots.txtにクロール制限は無く、PDF内にも再利用を禁じる記載は無いことを確認済み。蔵名・住所・都道府県といった事実情報のみを抽出する。

```bash
python3 scripts/scrape_beer_list.py    # PDFをダウンロード・解析し、beer_list_raw.jsonを生成
python3 scripts/geocode_beer_list.py   # 住所をNominatimでジオコーディングし、beer_list_geocoded.jsonを生成
```

- `scrape_beer_list.py`はPDFのテキスト抽出に`pdftotext`(poppler-utils)を使う。未インストールの場合は`brew install poppler`等でインストールする(Pythonコード自体は標準ライブラリのみ)。
- `geocode_beer_list.py`は`scripts/geocode_master_list.py`と全く同じジオコーディングロジック(1秒に1リクエストのレート制限、番地の段階的フォールバック、行政区画境目へのスペース挿入)を使う。データソースが異なるだけなので共通化はせず複製している。
- 備考欄に「閉店」「閉鎖」「業務終了」等の記載がある行(廃業した醸造所)は`scrape_beer_list.py`側で除外している。
- 結果は`beer_list_geocode_cache.json`にキャッシュされるため、途中で中断しても再実行時に再ジオコーディングをスキップできる。

## ワインデータについて

種別に「ワイン」を追加している。酒蔵・地ビールと同様、**OSM(Overpass API)**と、**日本ワイナリー協会(Japan Wineries Association)が公開する全国ワイナリー一覧**を組み合わせて取得している。`fetch_breweries.py`実行時に自動で統合され、`breweries.json`に`category="wine"`として保存される。

- 当初は国税庁が公開するデータを情報源にすることを検討したが、国税庁自身は個別ワイナリーの名称・住所を一覧できる構造化データを公開していない(「酒蔵マップ」は都道府県別の画像地図で個別ワイナリー名をテキストとして取得できず、「酒類等製造免許の新規取得者名等一覧」は2014年以降の新規免許取得者のみが対象で老舗ワイナリーが抜け落ちる上、「果実酒」区分がぶどうワインと梅酒・シードル等を区別しない)。そのため、清酒側の日本酒造組合中央会・地ビール側の北山産業と同じ位置づけの業界団体として、日本ワイナリー協会が紹介する全国のワイナリー一覧を情報源として使う。
- OSM側は`craft=winery`タグ(node/way)のみを検索範囲とする。`craft=brewery`と違って味噌・醤油蔵や飲食店との混同が実データ上見られなかったため、地ビール側のような名称・productタグによる絞り込みは行っていない。
- OSM単独では全国で80件に満たない程度(craft=wineryタグの登録状況に依存)しか拾えず、業界推定(全国400箇所以上)に遠く及ばないため、下記「ワイナリーマスターリストの更新方法」のリストで補っている。マスターリスト由来のレコードは住所をNominatimでジオコーディングした近似座標で、`wikipedia`は付与されない(`website`はマスターリスト側にも掲載されているため付与される)。
- 統合の突合ロジックは酒蔵・地ビールのマスターリストと同じ(正規化名+都道府県が一致、または都道府県が無い場合は正規化名+座標が100km以内)だが、`sake_info.json`のような銘柄解説データとの突合は行わない。
- 銘柄解説(金色ピン)の仕組みは今のところワインには適用していない(全件が通常ピンで表示される)。

## ワイナリーマスターリストの更新方法

日本ワイナリー協会(https://www.winery.or.jp/ )の「日本のワイナリー紹介」ページを情報源とする。エリア別14ページから個別ワイナリーの詳細ページを収集し、名称・所在地・ホームページを取得する。robots.txtにクロール制限は無く、解説文などの著作物は複製せず、名称・住所・ホームページURLといった事実情報のみを抽出する。

```bash
python3 scripts/scrape_winery_list.py    # 全14エリアをスクレイピングし、winery_list_raw.jsonを生成
python3 scripts/geocode_winery_list.py   # 住所をNominatimでジオコーディングし、winery_list_geocoded.jsonを生成
```

- どちらも標準ライブラリのみで書かれているため、pip installは不要。
- `scrape_winery_list.py`は住所から都道府県が判別できない場合に備え、政令指定都市名や都道府県名の省略表記からの推定、単一県のみのエリア(北海道・新潟・山梨・長野の各エリア)についてはエリア区分からの推定、という順にフォールバックする。
- `geocode_winery_list.py`は`scripts/geocode_beer_list.py`と全く同じジオコーディングロジックを使う。データソースが異なるだけなので共通化はせず複製している。
- 結果は`winery_list_geocode_cache.json`にキャッシュされるため、途中で中断しても再実行時に再ジオコーディングをスキップできる。

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

## 受賞歴データについて

清酒の蔵について、**全国新酒鑑評会**（独立行政法人酒類総合研究所(NRIB)と日本酒造組合中央会が共催する、100年以上続く最も権威のある清酒の公的コンテスト）の入賞歴を表示している。「受賞歴のある蔵のみ」トグルで絞り込め、該当する蔵のポップアップには入賞年（金賞の場合はその旨）が表示される。

- 対象は令和7酒造年度(2025年度、最新)から平成28酒造年度(2016年度)までの直近10年分。それ以前(平成14酒造年度まで遡れる)は蔵の統廃合・名称変更が進み、既存データとの突合精度が下がるため対象外にした。
- NRIBが公開する入賞酒目録PDF(https://www.nrib.go.jp/data/kan/shinshu/award/ )を情報源とする。目録に載っている酒は全て「入賞酒」で、うち特に成績が優秀なものに金賞(☆)が付く。robots.txtにクロール制限は無いことを確認済み。
- 目録は蔵単位ではなく出品酒単位のリストで、同じ蔵が複数の工場・タンクで複数回入賞することもあるが、突合時は蔵名の正規化名同士の部分一致(`sake_info.json`の突合と同じロジック)で1つの蔵にまとめ、年ごとの入賞・金賞状況を集約している。
- 焼酎・泡盛・地ビール・ワインには今のところ適用していない(清酒のみ)。

```bash
python3 scripts/scrape_sake_award_list.py   # 直近10年分のPDFを取得・解析し、sake_award_raw.jsonを生成
python3 fetch_breweries.py                  # sake_award_raw.jsonをbreweries.jsonに統合
```

- `scrape_sake_award_list.py`は標準ライブラリのみで書かれているが、PDFのテキスト抽出に`pdftotext`コマンド(poppler-utils)が別途必要。
- 蔵ごとの受賞歴は`breweries.json`の各清酒レコードに`award`フィールド(`{"years": [...], "gold_years": [...]}`、受賞が無い場合は`null`)として保存される。

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

- データ出典はOpenStreetMapと日本酒造組合中央会「酒蔵検索」、北山産業のクラフトビール醸造所リスト、日本ワイナリー協会の全国ワイナリー一覧、独立行政法人酒類総合研究所(NRIB)の全国新酒鑑評会入賞酒目録。網羅性は地域によって差がある。
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
├── beer_list_raw.json
├── beer_list_geocoded.json
├── beer_list_geocode_cache.json
├── winery_list_raw.json
├── winery_list_geocoded.json
├── winery_list_geocode_cache.json
├── sake_award_raw.json
├── manifest.json
├── sw.js
├── icons/
│   ├── icon-192.png
│   ├── icon-512.png
│   └── apple-touch-icon.png
├── scripts/
│   ├── generate_icons.py
│   ├── scrape_master_list.py
│   ├── geocode_master_list.py
│   ├── scrape_beer_list.py
│   ├── geocode_beer_list.py
│   ├── scrape_winery_list.py
│   ├── geocode_winery_list.py
│   └── scrape_sake_award_list.py
└── vendor/
    ├── leaflet/（leaflet.js, leaflet.css, images/）
    └── markercluster/（leaflet.markercluster.js, MarkerCluster*.css）
```
