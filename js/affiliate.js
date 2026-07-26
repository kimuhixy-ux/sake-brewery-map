(function () {
  "use strict";

  // 銘柄ごとに正確なASIN(具体的な商品ページ)を手入力する運用は、
  // 銘柄数(73件)・容量やラインナップの揺れを考えると現実的でないため、
  // 「銘柄名+種別」でAmazon検索結果に飛ばすリンクを生成する方式にする。
  const CATEGORY_SEARCH_KEYWORDS = {
    sake: "日本酒",
    shochu: "焼酎",
    awamori: "泡盛",
    beer: "クラフトビール",
    wine: "ワイン",
  };

  function buildAffiliateSearchLink(brand, category) {
    const tag = window.APP_CONFIG && window.APP_CONFIG.AMAZON_ASSOCIATE_TAG;
    if (!brand || !tag) return null;
    const keyword = CATEGORY_SEARCH_KEYWORDS[category] || "";
    const query = keyword ? `${brand} ${keyword}` : brand;
    return `https://www.amazon.co.jp/s?k=${encodeURIComponent(query)}&tag=${encodeURIComponent(tag)}`;
  }

  window.buildAffiliateSearchLink = buildAffiliateSearchLink;
})();
