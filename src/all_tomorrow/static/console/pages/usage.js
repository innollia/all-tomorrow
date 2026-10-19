"use strict";
// Subscription usage (Claude / Codex). The PC collector pushes: python -m all_tomorrow.usage push
(() => {
  const { esc, api, ago, left } = AT;
  AT.nav.push({ section: "모니터링", label: "구독 사용량", href: "#/usage", order: 60 });

  // A window whose reset time has passed is back to 0%, whatever the last observation said.
  const pctOf = w => left(w.resets_at) === null ? 0 : Math.round(w.percent);
  const bar = pct => `<div class="bar"><i class="${pct >= 80 ? "hi" : ""}" style="width:${Math.min(pct, 100)}%"></i></div>`;

  AT.home.push({ order: 30, render: async () => {
    const snap = await api("/api/usage").catch(() => null);
    if (!snap) return "";
    return snap.providers.map(p => {
      const rows = p.windows.map(w => `<div class="row small" style="justify-content:space-between;margin-top:6px"><span class="mute">${esc(w.label)}</span><span class="mono">${pctOf(w)}%</span></div>${bar(pctOf(w))}`).join("");
      const top = p.windows.length ? Math.max(...p.windows.map(pctOf)) + "%" : "-";
      const ok = p.status === "connected";
      return `<a class="card" href="#/usage"><div class="mute small">${esc(p.name)} 사용량${p.plan ? " · " + esc(p.plan) : ""}</div><div class="stat">${ok ? top : "-"}</div>${ok ? rows : `<div class="mute small">${esc(p.status)}</div>`}</a>`;
    }).join("");
  } });

  AT.pages["/usage"] = async () => {
    const snap = await api("/api/usage");
    if (!snap) return `<h1>구독 사용량</h1><div class="empty">데이터 없음. 로컬 PC에서 python -m all_tomorrow.usage push 실행 필요</div>`;
    const cards = snap.providers.map(p => {
      const ok = p.status === "connected";
      const rows = p.windows.map(w => {
        const l = left(w.resets_at), pct = pctOf(w);
        return `<div style="padding:8px 0"><div class="row" style="justify-content:space-between"><span>${esc(w.label)}</span><span class="mono mute">${pct}% · ${l === null ? "초기화됨" : l + " 후 초기화"}</span></div>${bar(pct)}</div>`;
      }).join("");
      const age = p.observed_at ? Math.round((Date.now() - new Date(p.observed_at)) / 60000) : 0;
      return `<div class="card"><div class="row" style="justify-content:space-between"><span><span class="t">${esc(p.name)}</span> <span class="mute small">${esc(p.plan)}</span></span><span class="dot ${ok ? "ok" : "bad"} small">${ok ? "연결됨" : esc(p.status)}</span></div>${rows || `<div class="empty">데이터 없음</div>`}${age > 30 ? `<div class="mute small">${ago(p.observed_at)} 관측값</div>` : ""}</div>`;
    }).join("");
    return `<h1>구독 사용량</h1><div class="sub">수집 ${ago(snap.collected_at)}</div><div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(300px,1fr))">${cards}</div>`;
  };
  AT.refresh["/usage"] = 60000;
})();
