/* Backup & maintenance: the Restore confirmation box. The server checks the typed word again before restoring anything. */
(function () {
  var modal = document.getElementById("restoreModal");
  if (!modal) return;
  var form = document.getElementById("restoreForm"), input = document.getElementById("restoreConfirm"), go = document.getElementById("restoreGo"), opener = null;
  function close() { modal.classList.remove("open"); if (opener) opener.focus(); }
  [].forEach.call(document.querySelectorAll("[data-restore]"), function (b) {
    b.addEventListener("click", function () {
      opener = b; form.action = b.getAttribute("data-url");
      document.getElementById("restoreWhen").textContent = b.getAttribute("data-when");
      input.value = ""; go.disabled = true; modal.classList.add("open"); input.focus();
    });
  });
  input.addEventListener("input", function () { go.disabled = input.value.trim() !== "RESTORE"; });
  document.getElementById("restoreCancel").addEventListener("click", close);
  modal.addEventListener("click", function (e) { if (e.target === modal) close(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && modal.classList.contains("open")) close(); });
})();
