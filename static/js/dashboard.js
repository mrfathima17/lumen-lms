/* Lecturer dashboard: a switch in a one-field form saves as soon as it is flipped. */
document.querySelectorAll("[data-autosubmit]").forEach(function (box) {
  box.addEventListener("change", function () { box.form.submit(); });
});
