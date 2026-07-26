(function () {
  "use strict";

  function renderDonateLink() {
    const username = window.APP_CONFIG && window.APP_CONFIG.KOFI_USERNAME;
    if (!username) return;
    const list = document.querySelector("#info-modal .modal-links");
    if (!list) return;
    const li = document.createElement("li");
    li.innerHTML = `<a href="https://ko-fi.com/${encodeURIComponent(username)}" target="_blank" rel="noopener">${window.S.kofiSupport}</a>`;
    list.appendChild(li);
  }

  renderDonateLink();
})();
