/* Theme & branding page: live preview while editing. Nothing is saved until the form is submitted;
   the server re-checks every value (colours, contrast, images) before it stores anything. */
(function () {
  var T0 = window.LumenTheme;
  if (!T0) return;
  var OPT = {};
  try { OPT = JSON.parse(document.getElementById("theme-options").textContent) || {}; } catch (e) {}
  function $(i) { return document.getElementById(i); }
  function isHex(v) { return /^#[0-9a-fA-F]{6}$/.test(v); }

  // Start from what the form holds (the saved theme, or what was just posted).
  var T = {
    brand: $("brandT").value, brand2: $("brand2T").value, sidebar: $("sidebarT").value,
    font: $("font").value, radius: +$("radius").value || 12, siteName: $("siteName").value,
    loginBg: "", logo: $("logoBox").getAttribute("data-src") || ""
  };
  var savedBg = (T0.get() || {}).loginBg || "";   // the theme the server rendered this page with (preset, colour or url(...))
  var loginBgField = $("loginBg"), imageActive = /^url\(/.test(savedBg);
  T.loginBg = savedBg;
  if (!imageActive && loginBgField.value && loginBgField.value !== savedBg) T.loginBg = loginBgField.value;

  function live() { T0.apply(T); paint(); }

  function paint() {
    $("radiusV").textContent = T.radius;
    $("pvName").textContent = T.siteName || "Lumen";
    ["logoBox", "pvLogo"].forEach(function (id) {
      var b = $(id);
      if (T.logo) { b.style.backgroundImage = "url('" + T.logo + "')"; b.textContent = ""; }
      else { b.style.backgroundImage = ""; b.textContent = (T.siteName || "L").charAt(0).toUpperCase(); }
    });
    [].forEach.call(document.querySelectorAll("#bgs button"), function (b, i) { b.classList.toggle("on", !imageActive && T.loginBg === OPT.backgrounds[i]); });
    [["brand", T.brand], ["brand2", T.brand2], ["sidebar", T.sidebar]].forEach(function (p) { if (isHex(p[1])) $(p[0]).value = p[1]; });
    if (!imageActive && isHex(T.loginBg)) $("bgColor").value = T.loginBg;
  }

  // ---- presets and backgrounds
  (OPT.presets || []).forEach(function (p) {
    var b = document.createElement("button"); b.type = "button";
    b.innerHTML = '<i style="background:linear-gradient(135deg,' + p[1] + ',' + p[2] + ')"></i>' + p[0];
    b.onclick = function () {
      T.brand = p[1]; T.brand2 = p[2]; T.sidebar = p[3];
      $("brandT").value = p[1]; $("brand2T").value = p[2]; $("sidebarT").value = p[3]; live();
    };
    $("presets").appendChild(b);
  });
  function chooseBackground(css) {          // a preset, a plain colour, or "" for the default
    imageActive = false; T.loginBg = css; loginBgField.value = css;
    $("loginBgData").value = ""; $("removeLoginImage").value = "1"; live();
  }
  (OPT.backgrounds || []).forEach(function (g) {
    var b = document.createElement("button"); b.type = "button"; b.style.background = g; b.setAttribute("aria-label", "Use this background");
    b.onclick = function () { chooseBackground(g); };
    $("bgs").appendChild(b);
  });
  $("bgColor").oninput = function () { chooseBackground(this.value); };
  $("bgClear").onclick = function () { chooseBackground(""); };

  // ---- colours: picker and hex box stay in step
  [["brand", "brand"], ["brand2", "brand2"], ["sidebar", "sidebar"]].forEach(function (k) {
    var n = k[0], key = k[1];
    $(n).oninput = function () { T[key] = this.value; $(n + "T").value = this.value; live(); };
    $(n + "T").oninput = function () { if (isHex(this.value)) { T[key] = this.value; live(); } };
  });
  $("siteName").oninput = function () { T.siteName = this.value; live(); };
  $("font").onchange = function () { T.font = this.value; live(); };
  $("radius").oninput = function () { T.radius = +this.value; live(); };

  // ---- images: shrunk in the browser, the server checks them again
  function shrink(file, max, type, q, cb) {
    var rd = new FileReader();
    rd.onload = function () {
      var im = new Image();
      im.onload = function () {
        var s = Math.min(1, max / Math.max(im.width, im.height)), c = document.createElement("canvas");
        c.width = Math.max(1, Math.round(im.width * s)); c.height = Math.max(1, Math.round(im.height * s));
        var x = c.getContext("2d");
        if (type === "image/jpeg") { x.fillStyle = "#fff"; x.fillRect(0, 0, c.width, c.height); }
        x.drawImage(im, 0, 0, c.width, c.height); cb(c.toDataURL(type, q));
      };
      im.onerror = function () { alert("That file is not a readable image."); };
      im.src = rd.result;
    };
    rd.readAsDataURL(file);
  }
  $("logoFile").onchange = function () {
    var f = this.files[0]; if (!f) return;
    shrink(f, 128, "image/png", 1, function (u) { T.logo = u; $("logoData").value = u; $("removeLogo").value = ""; live(); });
  };
  $("logoClear").onclick = function () { T.logo = ""; $("logoData").value = ""; $("removeLogo").value = "1"; $("logoFile").value = ""; live(); };
  $("bgFile").onchange = function () {
    var f = this.files[0]; if (!f) return;
    shrink(f, 1600, "image/jpeg", 0.8, function (u) {
      imageActive = true; T.loginBg = "url('" + u + "') center/cover no-repeat";
      loginBgField.value = ""; $("loginBgData").value = u; $("removeLoginImage").value = ""; live();
    });
  };

  // The dark-mode settings are not previewed: they are the default for everyone, not part of the look.
  live();
})();
