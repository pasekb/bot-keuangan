/**
 * Interaksi kecil dashboard: filter kategori berdasarkan tipe + konfirmasi hapus.
 * Tanpa dependensi eksternal.
 */
(function () {
  "use strict";

  function formOf(element) {
    return element && element.closest ? element.closest("form") : null;
  }

  function applyTypeFilter(form) {
    if (!form) return;
    var typeSelect = form.querySelector("[data-type-select]");
    var categorySelect = form.querySelector("[data-category-select]");
    if (!typeSelect || !categorySelect) return;

    var type = typeSelect.value;
    var selectedVisible = false;

    Array.prototype.forEach.call(categorySelect.options, function (option) {
      if (!option.value) return;
      var matches = option.dataset.type === type;
      option.hidden = !matches;
      option.disabled = !matches;
      if (option.selected && matches) selectedVisible = true;
    });

    if (!selectedVisible) categorySelect.value = "";
  }

  document.addEventListener("DOMContentLoaded", function () {
    Array.prototype.forEach.call(
      document.querySelectorAll("form"),
      applyTypeFilter
    );
  });

  document.addEventListener("change", function (event) {
    if (event.target.matches("[data-type-select]")) {
      applyTypeFilter(formOf(event.target));
    }
  });

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form || !form.dataset) return;
    var message = form.dataset.confirm;
    if (message && !window.confirm(message)) {
      event.preventDefault();
    }
  });
})();
