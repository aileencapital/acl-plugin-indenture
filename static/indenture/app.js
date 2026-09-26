/*
 * Minimal client behaviour for the indenture extractor.
 * - Toggles the preset-set dropdown visibility based on the selected mode.
 * - On form submit, shows a "processing" note and disables the submit
 *   button so the user does not double-submit a slow extraction.
 */
(function () {
  "use strict";

  function setPresetVisibility(mode) {
    var field = document.getElementById("preset-field");
    if (!field) return;
    if (mode === "preset") {
      field.classList.remove("hidden");
    } else {
      field.classList.add("hidden");
    }
  }

  function bindModeToggle() {
    var radios = document.querySelectorAll('input[type="radio"][name="mode"]');
    if (!radios.length) return;
    var current = "auto";
    radios.forEach(function (r) {
      if (r.checked) current = r.value;
      r.addEventListener("change", function () {
        if (r.checked) setPresetVisibility(r.value);
      });
    });
    setPresetVisibility(current);
  }

  function bindSubmitFeedback() {
    var form = document.getElementById("extract-form");
    if (!form) return;
    var btn = document.getElementById("submit-btn");
    var note = document.getElementById("processing-note");
    form.addEventListener("submit", function () {
      if (btn) {
        btn.disabled = true;
        btn.textContent = "Processing…";
      }
      if (note) note.hidden = false;
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    bindModeToggle();
    bindSubmitFeedback();
  });
})();
