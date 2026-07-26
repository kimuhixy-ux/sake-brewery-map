(function () {
  "use strict";

  // URLパス(/en/を含むか)からロケールを判定する
  var LOCALE = location.pathname.indexOf("/en/") !== -1 ? "en" : "ja";

  // 相対パスの基点。/en/配下のページから見て、data/やcss/などアプリ直下のファイルは1階層上になる
  var ROOT = LOCALE === "en" ? "../" : "./";

  window.APP_I18N = { LOCALE: LOCALE, ROOT: ROOT };
})();
