"use strict";
// Projects: list (#/projects) and detail (#/project/<id>) from the PC-pushed snapshot.
// The PC collector pushes: python -m all_tomorrow.projects_snapshot push
// Per-project panels live in /static/panels/<id>.js and set
// window.AT_PANELS[id] = (panel, project, {esc, list, ago}) => html; loaded only when that page opens.
(() => {
  const { esc, api, list, ago, loadScript } = AT;
  AT.nav.push({ section: "프로젝트", label: "프로젝트", href: "#/projects", order: 20 });
  AT.navAlias = Object.assign(AT.navAlias || {}, { "/project": "/projects" });
  window.AT_PANELS = window.AT_PANELS || {};

  async function loadPanel(id) {
    if (!window.AT_PANELS[id]) await loadScript(`/static/panels/${encodeURIComponent(id)}.js`);
    return window.AT_PANELS[id] || null;  // no custom panel: fall back to raw data
  }
  const links = p => (p.links || []).map(l => `<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)} ↗</a>`);

  AT.pages["/projects"] = async () => {
    const snap = await api("/api/project-snapshot");
    if (!snap) return `<h1>프로젝트</h1><div class="empty">데이터 없음. 로컬 PC에서 python -m all_tomorrow.projects_snapshot push 실행 필요</div>`;
    const rows = snap.projects.slice().sort((a, b) => String(b.last_activity || "").localeCompare(String(a.last_activity || ""))).map(p => {
      const g = p.git || {};
      const counts = {};
      (p.status_table || []).forEach(r => counts[r.status] = (counts[r.status] || 0) + 1);
      const badge = p.exists === false ? `<span class="pill">폴더 없음</span>` : g.problem ? `<span class="pill">git 문제</span>` : g.dirty_files ? `<span class="pill">변경 ${g.dirty_files}</span>` : "";
      return `<div><span class="k mono">${esc(p.last_activity || "-")}</span>
        <a href="#/project/${encodeURIComponent(p.id)}" style="flex:1">${esc(p.name)}${p.panel ? ' <span class="mute small">· 패널</span>' : ""}</a>
        <span class="small mute">${Object.entries(counts).map(([k, v]) => `${esc(k)} ${v}`).join(" · ")}</span>${badge}
        ${(p.links || []).map(l => `<a class="pill" href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)} ↗</a>`).join("")}</div>`;
    });
    return `<h1>프로젝트</h1><div class="sub">수집 ${ago(snap.collected_at)} · 최근 활동순</div>${list(rows)}`;
  };

  AT.pages["/project/"] = async id => {
    const snap = await api("/api/project-snapshot");
    const p = (snap?.projects || []).find(x => x.id === id);
    if (!p) return `<h1>프로젝트</h1><div class="empty">없는 프로젝트</div>`;
    const g = p.git;
    const facts = [
      ["최근 활동", p.last_activity || "-"],
      ...(p.exists === false ? [["폴더", "이 PC에 없음"]] : g ? (g.problem ? [["git", g.problem]] : [["브랜치", g.branch], ["마지막 커밋", `${g.last_commit} ${g.last_subject || ""}`], ["30일 커밋", g.commits_30d], ["미커밋 변경", g.dirty_files]]) : [["git", "저장소 아님"]]),
      ...(p.notes ? [["메모", p.notes]] : []),
    ].map(([k, v]) => `<div><span class="k">${esc(k)}</span><span>${esc(v)}</span></div>`);
    const table = (p.status_table || []).map(r => `<div><span style="flex:1">${esc(r.item)}</span><span class="pill">${esc(r.status)}</span></div>`);
    const raw = () => `<pre class="small mono">${esc(JSON.stringify(p.panel, null, 2))}</pre>`;
    let panel = "";
    if (p.panel) {
      if (p.panel.error) panel = `<div class="empty">패널 수집 실패: ${esc(p.panel.error)}</div>`;
      else {
        const render = await loadPanel(p.id);
        try { panel = render ? render(p.panel, p, { esc, list, ago }) : raw(); }
        catch (e) { panel = `<div class="empty">패널 표시 실패: ${esc(e.message)}</div>${raw()}`; }
      }
    }
    return `<h1>${esc(p.name)}</h1><div class="sub">${links(p).join(" · ") || "&nbsp;"}</div>
      ${list(facts)}${panel ? `<h2>패널</h2>${panel}` : ""}${table.length ? `<h2>상태표</h2>${list(table)}` : ""}`;
  };
})();
