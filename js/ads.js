(function () {
  "use strict";

  function initAds() {
    var config = window.APP_CONFIG;
    if (!config || !config.ADS_ENABLED || !config.ADSENSE_CLIENT_ID) return;

    const script = document.createElement("script");
    script.async = true;
    script.src =
      "https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=" +
      encodeURIComponent(config.ADSENSE_CLIENT_ID);
    script.crossOrigin = "anonymous";
    document.head.appendChild(script);
  }

  initAds();
})();
