/* Bulk enrolment: switching course reloads the "Currently enrolled" list; cohorts only apply to students; whole batches ask first. */
(function () {
  var form = document.getElementById("enrolForm");
  if (!form) return;
  var course = form.elements.course, role = form.elements.role, cohort = form.elements.cohort;
  course.addEventListener("change", function () { window.location = window.location.pathname + "?course=" + encodeURIComponent(course.value) + "&role=" + encodeURIComponent(role.value); });
  function sync() { cohort.disabled = role.value !== "student"; if (cohort.disabled) cohort.value = ""; }
  role.addEventListener("change", sync); sync();
  form.addEventListener("submit", function (e) {
    if (cohort.value) {
      var label = cohort.options[cohort.selectedIndex].text, where = course.options[course.selectedIndex].text;
      if (!confirm("Enrol everyone in " + label + " in " + where + "?")) e.preventDefault();
    }
  });
})();
