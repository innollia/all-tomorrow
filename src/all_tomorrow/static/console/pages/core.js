"use strict";
// Home page and links to the core server pages (requests, devices, account).
(() => {
  const { esc, api, list, ago } = AT;
  AT.nav.push(
    { section: "", label: "홈", href: "#/", order: 0 },
    { section: "요청", label: "요청·질문", href: "/requests", order: 10 },
    { section: "기기", label: "기기", href: "/devices", order: 80 },
    { section: "계정", label: "계정", href: "/account", order: 90 },
  );

  // Core tile: open questions and requested work from the control-plane API.
  AT.home.push({ order: 10, render: async () => {
    const d = await api("/api/overview").catch(() => null);
    if (!d) return "";
    const active = d.goals.filter(g => !g.terminal).length;
    return `<a class="card" href="/requests"><div class="mute small">답을 기다리는 질문</div><div class="stat">${d.questions.length}</div></a>
            <a class="card" href="/requests"><div class="mute small">진행 중인 요청</div><div class="stat">${active}</div></a>`;
  } });
  AT.home.push({ order: 20, render: async () => {
    const devs = await api("/api/devices").catch(() => null);
    if (!devs) return "";
    const on = devs.filter(d => d.status === "ONLINE").length;
    return `<a class="card" href="/devices"><div class="mute small">켜진 기기</div><div class="stat">${on} / ${devs.filter(d => d.status !== "REVOKED").length}</div></a>`;
  } });

  AT.pages["/"] = async () => {
    const tiles = await Promise.all(AT.home.slice().sort((a, b) => a.order - b.order).map(t => t.render().catch(() => "")));
    const devs = await api("/api/devices").catch(() => []);
    const rows = devs.filter(d => d.status !== "REVOKED").map(d =>
      `<div><span class="k dot ${d.status === "ONLINE" ? "ok" : "bad"}">${esc(d.status === "ONLINE" ? "온라인" : "오프라인")}</span><span style="flex:1">${esc(d.name)}</span><span class="mute small">${d.last_heartbeat_at ? ago(d.last_heartbeat_at) : "신호 없음"}</span></div>`);
    return `<h1>홈</h1><div class="sub">지금 상태 요약</div><div class="grid">${tiles.join("")}</div>
      <h2>기기</h2>${list(rows)}`;
  };
  AT.refresh["/"] = 15000;
})();
