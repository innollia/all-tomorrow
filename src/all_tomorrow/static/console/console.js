"use strict";
// Console core: registries, helpers and the hash router. Feature files in pages/ register into
// AT.pages / AT.nav / AT.home; this file never needs editing when a feature is added.
const AT = window.AT = {
  pages: {},   // "/path" -> async (arg) => html ; "/path/:arg" handled via AT.pages["/path/"]
  nav: [],     // {section, label, href, order}; href "#/x" for console pages, "/x" for server pages
  home: [],    // {order, render: async () => html} tiles on the home page
  refresh: {}, // "/path" -> ms auto-refresh interval
};
const $ = (s, el = document) => el.querySelector(s);
const view = $("#view");
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => "&#" + c.charCodeAt(0) + ";");
async function api(path, body, method) {
  const opts = body === undefined && !method ? {} : { method: method || "POST", headers: { "content-type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) };
  const r = await fetch(path, opts);
  if (r.status === 401) { location = "/login"; throw new Error("auth"); }
  if (!r.ok) { const t = await r.text(); throw new Error(r.status + " " + t.slice(0, 200)); }
  return r.status === 204 ? null : r.json();
}
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.style.display = "block"; clearTimeout(t._h); t._h = setTimeout(() => t.style.display = "none", 3000); }
function ago(ts) { const m = Math.round((Date.now() - new Date(ts)) / 60000); return m < 1 ? "방금" : m < 60 ? m + "분 전" : m < 1440 ? Math.round(m / 60) + "시간 전" : Math.round(m / 1440) + "일 전"; }
function left(t) { const ms = new Date(t) - Date.now(); if (!(ms > 0)) return null; const m = Math.floor(ms / 60000), d = Math.floor(m / 1440), h = Math.floor(m % 1440 / 60); return d ? `${d}일 ${h}시간` : h ? `${h}시간 ${m % 60}분` : `${m % 60}분`; }
const list = items => items.length ? `<div class="list">${items.join("")}</div>` : `<div class="empty">없음</div>`;
const scripts = {};
function loadScript(src) {  // lazy-load a feature's extra JS (e.g. project panels) once
  scripts[src] = scripts[src] || new Promise(resolve => {
    const s = document.createElement("script"); s.src = src;
    s.onload = () => resolve(true); s.onerror = () => resolve(false);
    document.head.appendChild(s);
  });
  return scripts[src];
}
Object.assign(AT, { $, view, esc, api, toast, ago, left, list, loadScript });

// ---------------------------------------------------------------- nav + router
function buildNav() {
  const sections = {};
  AT.nav.slice().sort((a, b) => (a.order ?? 50) - (b.order ?? 50)).forEach(n => (sections[n.section || ""] = sections[n.section || ""] || []).push(n));
  $("#navlinks").innerHTML = Object.entries(sections).map(([sec, items]) =>
    (sec ? `<div class="sec">${esc(sec)}</div>` : "") + items.map(n => `<a href="${esc(n.href)}">${esc(n.label)}</a>`).join("")).join("");
}
function parseHash() {
  const h = location.hash.slice(1) || "/";
  const m = h.match(/^(\/[^/]+)\/(.+)$/);  // "/project/x" -> page "/project/" with arg "x"
  if (m && AT.pages[m[1] + "/"]) return [m[1] + "/", decodeURIComponent(m[2]), m[1]];
  return [h, undefined, h];
}
let timer = null;
async function render() {
  const [key, arg, navKey] = parseHash();
  clearTimeout(timer);
  const navHref = "#" + (AT.navAlias?.[navKey] || navKey);
  document.querySelectorAll("#navlinks a").forEach(a => a.classList.toggle("on", a.getAttribute("href") === navHref));
  $("#nav").classList.remove("open");
  const page = AT.pages[key] || AT.pages["/"];
  try { view.innerHTML = await page(arg); } catch (e) { if (e.message !== "auth") view.innerHTML = `<h1>오류</h1><div class="empty">${esc(e.message)}</div>`; }
  const every = AT.refresh[key];
  // Polling stops while the tab is hidden or while the user is typing; the server is small.
  if (every && !document.hidden) timer = setTimeout(() => {
    const busy = document.activeElement && view.contains(document.activeElement) && document.activeElement.tagName !== "BUTTON";
    busy ? (timer = setTimeout(render, every)) : render();
  }, every);
}
AT.render = render;
$("#navsearch").addEventListener("input", e => {
  const q = e.target.value.trim();
  document.querySelectorAll("#navlinks a").forEach(a => a.style.display = !q || a.textContent.includes(q) ? "" : "none");
  document.querySelectorAll("#navlinks .sec").forEach(s => s.style.display = q ? "none" : "");
});
$("#menu").addEventListener("click", () => $("#nav").classList.toggle("open"));
$("#logout").addEventListener("click", async () => { await fetch("/api/logout", { method: "POST" }); location = "/login"; });
window.addEventListener("hashchange", render);
document.addEventListener("visibilitychange", () => { if (!document.hidden && AT.refresh[parseHash()[0]]) render(); });
window.addEventListener("load", () => { buildNav(); render(); });
