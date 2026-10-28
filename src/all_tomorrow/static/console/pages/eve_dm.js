"use strict";
// Eve 해금 사용자 DM: 사람별 목록 → 그 사람과 이브의 대화(오래된 것부터). API: /api/eve-dm (console/eve_dm.py).
(() => {
  const { esc, api, ago, list } = AT;
  AT.nav.push({ section: "Eve", label: "해금 사용자 DM", href: "#/eve-dm", order: 70 });
  AT.navAlias = Object.assign(AT.navAlias || {}, { "/eve-dm-user": "/eve-dm" });
  const name = p => esc(p.user_name || p.user_id);
  const stateText = p => p.state === "revoked" ? '<span class="pill warn">회수됨</span>' : '<span class="pill">해금</span>';
  const when = t => t ? ago(new Date(t)) : "";

  AT.pages["/eve-dm"] = async () => {
    const people = await api("/api/eve-dm");
    const rows = people.map(p => `<a class="idea-row" href="#/eve-dm-user/${encodeURIComponent(p.user_id)}">
      <span class="idea-row-title">${name(p)} ${stateText(p)}</span>
      <span class="small mute">대화 ${p.turns}${p.last_at ? " · " + when(p.last_at) : ""}${p.last_text ? " · " + esc(p.last_text.slice(0, 60)) : ""}</span></a>`);
    return `<h1>Eve 해금 사용자 DM</h1>
      <div class="sub">유료 DM을 해금한 사람과 이브의 대화. 회수해도 기록은 남고 '회수됨'으로 보인다. 비밀값으로 보이는 것은 저장 전에 가린다.</div>
      ${rows.length ? list(rows) : '<div class="empty">아직 받은 대화가 없다.</div>'}`;
  };

  AT.pages["/eve-dm-user/"] = async id => {
    const c = await api(`/api/eve-dm/${encodeURIComponent(id)}`);
    const turn = t => `<div class="card" style="margin-top:8px;${t.role === "eve" ? "margin-left:24px" : "margin-right:24px"}">
      <div class="row small mute"><b>${t.role === "eve" ? "이브" : name(c)}</b><span>${esc(new Date(t.created_at).toLocaleString())}</span></div>
      <div style="white-space:pre-wrap;margin-top:4px">${esc(t.content)}</div></div>`;
    return `<div class="small"><a href="#/eve-dm">← 해금 사용자 DM</a></div>
      <h1>${name(c)} ${stateText(c)}</h1>
      <div class="sub mono small">${esc(c.user_id)}${c.state_at ? " · 상태 " + when(c.state_at) : ""} · 대화 ${c.turns.length}</div>
      ${c.turns.length ? c.turns.map(turn).join("") : '<div class="empty">대화 없음</div>'}`;
  };
})();
