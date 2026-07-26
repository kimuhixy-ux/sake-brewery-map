(function () {
  "use strict";

  const infoBtn = document.getElementById("info-btn");
  const infoModal = document.getElementById("info-modal");
  const closeBtn = document.getElementById("info-modal-close");

  function openModal() {
    infoModal.hidden = false;
  }
  function closeModal() {
    infoModal.hidden = true;
  }

  infoBtn.addEventListener("click", openModal);
  closeBtn.addEventListener("click", closeModal);
  infoModal.addEventListener("click", (e) => {
    if (e.target === infoModal) closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !infoModal.hidden) closeModal();
  });
})();
