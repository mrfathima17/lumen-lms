/* Lumen theme: dark mode + admin branding. Loaded in <head> on every page.
   Prototype note: settings live in this browser's localStorage. In the PHP/MySQL version,
   branding is stored site-wide in the database and dark mode per user. */
(function () {
  var KEY = "lumenTheme", MODE = "lumenMode", r = document.documentElement;
  var DEFAULT = {
    siteName: "Lumen", brand: "#4f46e5", brand2: "#7c3aed", sidebar: "#14172b",
    font: "system", radius: 12, loginBg: "", logo: "", defaultMode: "light", allowDark: true
  };
  var FONTS = {
    system: "Inter,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif",
    Inter: "'Inter',system-ui,sans-serif", Poppins: "'Poppins',system-ui,sans-serif", Nunito: "'Nunito',system-ui,sans-serif",
    Roboto: "'Roboto',system-ui,sans-serif", Merriweather: "'Merriweather',Georgia,serif"
  };
  function read(k) { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } }
  function write(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch (e) { return false; } }
  // Branding comes from the server (site settings), never from this browser; only dark/light mode is remembered per person.
  var SERVER = {};
  try { SERVER = JSON.parse(document.getElementById("lumen-theme-data").textContent) || {}; } catch (e) {}
  for (var sk in SERVER) { if (SERVER[sk] !== null && SERVER[sk] !== undefined) DEFAULT[sk] = SERVER[sk]; }
  function get() {
    var t = {}, o = {};
    for (var k in DEFAULT) o[k] = (t[k] !== undefined && t[k] !== null) ? t[k] : DEFAULT[k];
    return o;
  }
  function loadFont(f) {
    if (f === "system" || !FONTS[f]) return;
    if (document.getElementById("lumen-font")) document.getElementById("lumen-font").remove();
    var l = document.createElement("link"); l.id = "lumen-font"; l.rel = "stylesheet";
    l.href = "https://fonts.googleapis.com/css2?family=" + f + ":wght@400;500;600;700&display=swap";
    (document.head || r).appendChild(l);
  }
  function apply(t) {
    t = t || get();
    r.style.setProperty("--brand", t.brand);
    r.style.setProperty("--brand-2", t.brand2);
    r.style.setProperty("--sidebar", t.sidebar);
    r.style.setProperty("--radius", t.radius + "px");
    r.style.setProperty("--font", FONTS[t.font] || FONTS.system);
    if (t.loginBg) r.style.setProperty("--login-bg", t.loginBg); else r.style.removeProperty("--login-bg");
    if (t.brand.toLowerCase() !== "#4f46e5") r.setAttribute("data-custom-brand", ""); else r.removeAttribute("data-custom-brand");
    loadFont(t.font);
  }
  function currentMode() {
    var t = get(), m = null;
    try { m = localStorage.getItem(MODE); } catch (e) {}
    if (!t.allowDark) m = t.defaultMode === "dark" ? "dark" : "light";
    if (!m) {
      m = t.defaultMode;
      if (m === "system") m = (window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches) ? "dark" : "light";
    }
    return m === "dark" ? "dark" : "light";
  }
  function setMode(m, remember) {
    if (m === "dark") r.setAttribute("data-theme", "dark"); else r.removeAttribute("data-theme");
    if (remember) { try { localStorage.setItem(MODE, m); } catch (e) {} }
    var b = document.querySelectorAll("[data-theme-toggle]");
    for (var i = 0; i < b.length; i++) paint(b[i]);
  }
  function toggle() { setMode(r.getAttribute("data-theme") === "dark" ? "light" : "dark", true); }
  function paint(el) {
    var d = r.getAttribute("data-theme") === "dark";
    el.innerHTML = window.LumenIcon ? window.LumenIcon(d ? "sun" : "moon") : (d ? "Light" : "Dark");
    el.title = d ? "Switch to light mode" : "Switch to dark mode";
    el.setAttribute("aria-label", el.title);
  }
  function mount() {
    if (!get().allowDark) return;
    var el = document.querySelector("[data-theme-toggle]");
    if (!el) {
      var host = document.querySelector(".topbar .right");
      el = document.createElement("button"); el.type = "button"; el.setAttribute("data-theme-toggle", ""); el.className = "theme-btn";
      if (host) host.insertBefore(el, host.firstChild); else { el.className += " floating"; document.body.appendChild(el); }
    }
    el.onclick = toggle; paint(el);
  }
  apply(); setMode(currentMode(), false);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount); else mount();
  window.LumenTheme = {
    DEFAULT: DEFAULT, FONTS: FONTS, get: get, apply: apply, toggle: toggle, setMode: setMode, currentMode: currentMode,
    save: function (t) { return write(KEY, t); },
    reset: function () { try { localStorage.removeItem(KEY); localStorage.removeItem(MODE); } catch (e) {} apply(DEFAULT); setMode("light", false); }
  };
})();
