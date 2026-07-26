(function () {
  "use strict";

  var en = window.APP_I18N && window.APP_I18N.LOCALE === "en";

  window.S = {
    appTitle: en ? "Japan Sake Brewery Map" : "全国酒蔵マップ",
    searchPlaceholder: en ? "Search by brewery or brand name…" : "蔵名・銘柄名で検索…",
    prefAll: en ? "Prefecture: All" : "都道府県: すべて",
    categoryAll: en ? "Type: All" : "種別: すべて",
    categoryLabels: {
      sake: en ? "Sake" : "清酒",
      shochu: en ? "Shochu" : "焼酎",
      awamori: en ? "Awamori" : "泡盛",
      beer: en ? "Craft Beer" : "地ビール",
      wine: en ? "Wine" : "ワイン",
    },
    awardCompetitionLabels: {
      sake: en ? "National New Sake Appraisal" : "全国新酒鑑評会",
      wine: en ? "Japan Wine Competition" : "日本ワインコンクール",
      beer: en ? "International Beer Cup" : "インターナショナル・ビアカップ",
      fallback: en ? "Award" : "受賞歴",
    },
    featuredToggle: en ? "🏵 Featured breweries only" : "🏵 銘柄解説のある蔵のみ",
    awardToggle: en ? "🏆 Award-winning breweries only" : "🏆 受賞歴のある蔵のみ",
    resultCount: function (count, total) {
      return en ? count + " shown (of " + total + ")" : count + "件表示中(全" + total + "件)";
    },
    locateBtnTitle: en ? "Go to current location" : "現在地に移動",
    infoBtnTitle: en ? "About this app" : "このアプリについて",
    modalCloseLabel: en ? "Close" : "閉じる",
    modalTitle: en ? "Japan Sake Brewery Map" : "全国酒蔵マップ",
    modalDesc: en
      ? "A PWA for finding sake breweries, wineries, and craft beer breweries across Japan using OpenStreetMap data."
      : "全国の酒蔵・ワイナリー・地ビール醸造所をOpenStreetMapのデータで探せるPWAです。",
    aboutLink: en ? "About" : "運営者情報",
    privacyLink: en ? "Privacy Policy" : "プライバシーポリシー",
    kofiSupport: en ? "☕ Support on Ko-fi" : "☕ Ko-fiで応援する",
    mapOpenBtn: en ? "📍 Open in Maps" : "📍 マップで開く",
    routeBtn: en ? "🚗 Directions" : "🚗 経路",
    officialSiteBtn: en ? "Official Site" : "公式サイト",
    findOnAmazon: function (brand) {
      return en ? "Find " + brand : brand + "を探す";
    },
    prLabel: "PR",
    awardYearsLabel: function (competitionName, yearsText) {
      return en ? "🏆 " + competitionName + " awards: " + yearsText : "🏆 " + competitionName + " 入賞歴: " + yearsText;
    },
    goldYearSuffix: en ? " (Gold)" : "年(金賞)",
    yearSuffix: en ? "" : "年",
    locateError: en
      ? "Could not get your current location. Please allow location access."
      : "現在地を取得できませんでした。位置情報の利用を許可してください。",
    dataLoadError: en ? "Failed to load the data." : "データの読み込みに失敗しました",
  };
})();
