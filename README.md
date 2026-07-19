# sake-brewery-map（全国酒蔵マップ）

全国の酒蔵をOpenStreetMapのデータで1枚の地図にプロットするPWA。サーバー不要の静的サイトで、ビルドツールも使わない。有名な酒蔵・銘柄には解説を表示する。

## 使い方（iPhoneでホーム画面に追加）

1. iPhoneのSafariで公開URL（GitHub Pagesのアドレス）を開く
2. 地図が表示されたら共有ボタン（□に↑）をタップ
3. 「ホーム画面に追加」を選択

これでアイコンをタップするだけで単独アプリのように起動する。

## 機能

- Leaflet.js + OpenStreetMapタイルによる地図表示、マーカーはクラスタリング対応
- 銘柄解説がある蔵は金色ピン、それ以外は藍色ピンで区別
- 蔵名・銘柄名で検索、都道府県で絞り込み、「銘柄解説のある蔵のみ」トグル
- ポップアップに蔵名・代表銘柄・特徴解説・住所・「マップで開く」「経路」（Apple純正マップに連携）・公式サイト/Wikipediaへのリンクを表示
- 現在地ボタン
- PWA対応（ホーム画面に追加してオフラインでも地図UI自体は起動可能。地図タイル自体はオンラインが必要）

## データの更新方法

酒蔵の位置データはOpenStreetMap（Overpass API）から取得した静的JSON（`breweries.json`）。実行時にAPIを呼び出さない設計のため、最新化するには以下を実行する。

```bash
python3 fetch_breweries.py
```

- 標準ライブラリのみ（`urllib`）で書かれているため、pip installは不要。
- Overpass APIには負荷制限があるため、エンドポイントを2つ用意し、失敗時は待機してリトライ、それでもダメなら別エンドポイントに切り替える（最大で数分かかることがある）。
- `craft=sake_brewery`タグはOSM上でほとんど使われていないため、それとは別に「タグの種類を問わず、名称に酒造・酒蔵・銘醸を含む施設」を全国から検索する方式にしている（名称インデックスを使うため、この方式でないとOverpass側のタイムアウトに掛かりやすい）。
- 居酒屋・飲食店（`amenity=restaurant`等）や、「住宅公園」「ハウジング」「ドライブイン」といった、名称に酒造/酒蔵を含むだけの無関係な施設は除外している。
- 同じ蔵が複数のタグ種別（`craft`/`shop`/`landuse`/`building`など）で重複して登録されていることがあるため、正規化した名称が同じで座標も近い（約1km以内）ものは1件にまとめている。
- `sake_info.json`（下記）と名称・都道府県で突き合わせ、一致した蔵には`featured: true`と銘柄名・解説が付く。
- 実行結果は標準出力に「取得件数」「銘柄情報がマッチした件数」が表示される。

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

- データ出典はOpenStreetMapであり、網羅性は地域によって差がある。有名な酒蔵でもOSM上に登録がない、または検索キーワード（酒造・酒蔵・銘醸）を含まない名称で登録されている場合は地図に表示されない。
- 検索範囲を広げるため、`craft`タグに限らずタグの種類を問わず名称一致で検索している。そのため、まれに酒蔵とは無関係な施設（同じ名称を含む店舗など）が紛れ込む可能性がある（気づいた場合は`fetch_breweries.py`の`NOISE_NAME_KEYWORDS`に除外キーワードを追加する）。
- 都道府県（`pref`）はOSMタグ（`addr:province`等）がある場合のみ入る。ない場合は`null`となり、都道府県での絞り込みには出てこない。
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
├── manifest.json
├── sw.js
├── icons/
│   ├── icon-192.png
│   ├── icon-512.png
│   └── apple-touch-icon.png
├── scripts/
│   └── generate_icons.py
└── vendor/
    ├── leaflet/（leaflet.js, leaflet.css, images/）
    └── markercluster/（leaflet.markercluster.js, MarkerCluster*.css）
```
