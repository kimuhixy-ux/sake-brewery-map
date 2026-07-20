(function () {
  "use strict";

  const map = L.map("map", {
    zoomControl: true,
    attributionControl: true,
  }).setView([36.5, 138.0], 6);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  const clusterGroup = L.markerClusterGroup({
    maxClusterRadius: 50,
  });
  map.addLayer(clusterGroup);

  const searchInput = document.getElementById("search-input");
  const prefSelect = document.getElementById("pref-select");
  const categorySelect = document.getElementById("category-select");
  const featuredToggle = document.getElementById("featured-toggle");
  const resultCount = document.getElementById("result-count");
  const locateBtn = document.getElementById("locate-btn");

  let breweries = [];
  let featuredOnly = false;

  // 金色(銘柄解説あり)と藍色(通常)のピン色はそのまま維持しつつ、
  // 清酒(丸)/焼酎(ひし形)/泡盛(三角)は中心のマーカー形状で区別する。
  // 画像ファイルを使わずコード内で生成することで、余計なアセット管理を避ける。
  const CATEGORY_MARKS = {
    sake: '<circle cx="14" cy="14" r="5.5" fill="#fff"/>',
    shochu: '<rect x="9.5" y="9.5" width="9" height="9" fill="#fff" transform="rotate(45 14 14)"/>',
    awamori: '<polygon points="14,8 19.5,18 8.5,18" fill="#fff"/>',
  };

  function makeIcon(featured, category) {
    const color = featured ? "#d4af37" : "#22334a";
    const mark = CATEGORY_MARKS[category] || CATEGORY_MARKS.sake;
    const svg = `
      <svg width="28" height="38" viewBox="0 0 28 38" xmlns="http://www.w3.org/2000/svg">
        <path d="M14 0C6.3 0 0 6.3 0 14c0 10.5 14 24 14 24s14-13.5 14-24C28 6.3 21.7 0 14 0z" fill="${color}" stroke="#fff" stroke-width="1.5"/>
        ${mark}
      </svg>`;
    return L.divIcon({
      className: "brewery-icon",
      html: svg,
      iconSize: [28, 38],
      iconAnchor: [14, 38],
      popupAnchor: [0, -34],
    });
  }

  const icons = {};
  Object.keys(CATEGORY_MARKS).forEach((category) => {
    icons[category] = { normal: makeIcon(false, category), featured: makeIcon(true, category) };
  });
  const CATEGORY_LABELS = { sake: "清酒", shochu: "焼酎", awamori: "泡盛" };

  function escapeHtml(str) {
    if (!str) return "";
    return str.replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  // ポップアップの中身を組み立てる。
  // 銘柄情報がある蔵は「代表銘柄名(大きく表示)+特徴解説」を先頭に出す。
  function buildPopupHtml(b) {
    const appleMapsUrl = `https://maps.apple.com/?q=${encodeURIComponent(b.name)}&ll=${b.lat},${b.lon}`;
    const routeUrl = `https://maps.apple.com/?daddr=${b.lat},${b.lon}`;

    let html = '<div class="brewery-popup">';
    html += `<p class="popup-name">${escapeHtml(b.name)}`;
    if (b.category) {
      html += ` <span class="popup-category popup-category-${escapeHtml(b.category)}">${escapeHtml(CATEGORY_LABELS[b.category] || b.category)}</span>`;
    }
    html += "</p>";
    if (b.featured && b.brand) {
      html += `<p class="popup-brand">${escapeHtml(b.brand)}</p>`;
      if (b.desc) {
        html += `<p class="popup-desc">${escapeHtml(b.desc)}</p>`;
      }
    }
    if (b.address) {
      html += `<p class="popup-address">${escapeHtml(b.address)}</p>`;
    }
    html += '<div class="popup-buttons">';
    html += `<a href="${escapeHtml(appleMapsUrl)}" target="_blank" rel="noopener">📍 マップで開く</a>`;
    html += `<a href="${escapeHtml(routeUrl)}" target="_blank" rel="noopener">🚗 経路</a>`;
    if (b.website) {
      html += `<a class="secondary" href="${escapeHtml(b.website)}" target="_blank" rel="noopener">公式サイト</a>`;
    }
    if (b.wikipedia) {
      html += `<a class="secondary" href="${escapeHtml(b.wikipedia)}" target="_blank" rel="noopener">Wikipedia</a>`;
    }
    html += "</div></div>";
    return html;
  }

  function matchesFilters(b, query, pref, category) {
    if (featuredOnly && !b.featured) return false;
    if (pref && b.pref !== pref) return false;
    if (category && b.category !== category) return false;
    if (query) {
      const haystack = `${b.name} ${b.brand || ""}`.toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    return true;
  }

  // 検索・都道府県・カテゴリ・トグルの条件に合うものだけをクラスタに出し直す。
  function render() {
    const query = searchInput.value.trim().toLowerCase();
    const pref = prefSelect.value;
    const category = categorySelect.value;

    clusterGroup.clearLayers();
    let count = 0;
    breweries.forEach((b) => {
      if (!matchesFilters(b, query, pref, category)) return;
      const iconSet = icons[b.category] || icons.sake;
      const marker = L.marker([b.lat, b.lon], {
        icon: b.featured ? iconSet.featured : iconSet.normal,
      });
      // ヘッダー+検索パネルが画面上部を覆っているため、ポップアップが
      // その下に隠れないよう自動パン時の上余白を広めに確保する。
      marker.bindPopup(buildPopupHtml(b), {
        autoPanPaddingTopLeft: L.point(10, 220),
        autoPanPaddingBottomRight: L.point(10, 10),
      });
      clusterGroup.addLayer(marker);
      count += 1;
    });
    resultCount.textContent = `${count}件表示中(全${breweries.length}件)`;
  }

  function populatePrefSelect() {
    const prefs = Array.from(new Set(breweries.map((b) => b.pref).filter(Boolean))).sort();
    prefs.forEach((pref) => {
      const opt = document.createElement("option");
      opt.value = pref;
      opt.textContent = pref;
      prefSelect.appendChild(opt);
    });
  }

  fetch("breweries.json")
    .then((res) => res.json())
    .then((data) => {
      breweries = data;
      populatePrefSelect();
      render();
    })
    .catch((err) => {
      console.error("酒蔵データの読み込みに失敗しました", err);
      resultCount.textContent = "データの読み込みに失敗しました";
    });

  searchInput.addEventListener("input", render);
  prefSelect.addEventListener("change", render);
  categorySelect.addEventListener("change", render);
  featuredToggle.addEventListener("click", () => {
    featuredOnly = !featuredOnly;
    featuredToggle.setAttribute("aria-pressed", String(featuredOnly));
    render();
  });

  locateBtn.addEventListener("click", () => {
    map.locate({ setView: true, maxZoom: 14 });
  });
  map.on("locationerror", () => {
    alert("現在地を取得できませんでした。位置情報の利用を許可してください。");
  });
})();
