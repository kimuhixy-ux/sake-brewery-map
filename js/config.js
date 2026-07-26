(function () {
  "use strict";

  window.APP_CONFIG = {
    AMAZON_ASSOCIATE_TAG: "kimuhixy-22",
    // Ko-fiのユーザー名。未設定(空文字)の間は寄付リンクを表示しない
    KOFI_USERNAME: "kimuhixy",
    // AdSense広告はカスタムドメイン(kimuhixy.com)経由のアクセス時のみ表示する
    // (GitHub Pages / Cloudflare Pagesの単体URLでは重複コンテンツ扱いを避けるため表示しない)
    ADS_ENABLED: location.hostname === "kimuhixy.com",
    ADSENSE_CLIENT_ID: "ca-pub-3562055879455682",
  };
})();
