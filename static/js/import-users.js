/* Bulk user import: choosing or dropping a file checks it straight away; changing the role or the skip switch re-checks the same file. */
(function () {
  var form = document.getElementById("importForm"), dz = document.getElementById("dz"), input = document.getElementById("csvFile");
  if (!form || !input) return;
  var hasText = !!form.elements.text;
  input.addEventListener("change", function () { if (input.files.length) form.submit(); });
  ["dragenter", "dragover"].forEach(function (ev) { dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.add("over"); }); });
  ["dragleave", "drop"].forEach(function (ev) { dz.addEventListener(ev, function () { dz.classList.remove("over"); }); });
  dz.addEventListener("drop", function (e) {
    e.preventDefault();
    if (e.dataTransfer && e.dataTransfer.files.length) { input.files = e.dataTransfer.files; form.submit(); }
  });
  if (hasText) {
    [form.elements.default_role, form.elements.skip_existing].forEach(function (el) { if (el) el.addEventListener("change", function () { form.submit(); }); });
  }
})();
