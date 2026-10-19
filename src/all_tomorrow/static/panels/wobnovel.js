"use strict";
// wobnovel panel: implementation log, Studio DB, canonical Muvel works. Data from project_panels/wobnovel.py.
window.AT_PANELS = window.AT_PANELS || {};
window.AT_PANELS["wobnovel"] = (panel, project, h) => {
  const { esc, list, ago } = h;
  const when = ts => ts ? ago(ts) : "-";
  const RUN = { queued: "대기", running: "실행중", succeeded: "성공", failed: "실패", canceled: "취소", interrupted: "중단" };
  const stat = (label, value, note) => `<div class="card"><div class="mute small">${esc(label)}</div><div class="stat">${esc(value ?? "-")}</div>${note ? `<div class="mute small">${esc(note)}</div>` : ""}</div>`;

  const s = panel.status, st = panel.studio, w = panel.works || { items: [] };
  const studioOk = st && !st.error;
  const works = w.items || [];
  const episodes = works.reduce((n, x) => n + (x.episodes || 0), 0);

  const stats = `<div class="grid">${[
    stat("최신 기록 미확인", s ? s.unverified : "-", s ? s.date : "status.md 없음"),
    stat("승인 대기", studioOk ? st.approvals_pending : "-", "Studio"),
    stat("Studio 실행", studioOk ? st.runs : "-", studioOk ? `세션 ${st.sessions ?? "-"} · 리비전 ${st.revisions ?? "-"}` : ""),
    stat("작품 회차", w.found ? episodes : "-", w.found ? `작품 ${works.length}` : "MuvelProjects 없음"),
  ].join("")}</div>`;

  const log = !s ? `<div class="empty">docs/tracking/status.md 없음</div>` : list((s.recent || []).map(r =>
    `<div><span class="k mono">${esc(r.date || "-")}</span><span style="flex:1">${esc(r.title)}</span>${r.unverified ? `<span class="pill">미확인 ${esc(r.unverified)}</span>` : ""}</div>`));

  const studio = !st ? `<div class="empty">Studio DB 없음</div>`
    : st.error ? `<div class="empty">Studio DB 읽기 실패: ${esc(st.error)}</div>`
    : list((st.recent_runs || []).map(r =>
      `<div><span class="k mono">${esc(r.id)}</span><span style="flex:1">${esc(r.work || "작품 미상")}${r.engine ? ` <span class="mute small">· ${esc(r.engine)}</span>` : ""}</span><span class="small mute">${esc(when(r.at))}</span><span class="pill">${esc(RUN[r.status] || r.status)}</span></div>`));

  const workRows = !w.found ? `<div class="empty">MuvelProjects 폴더 없음</div>` : list(works.map(x =>
    `<div><span style="flex:1;min-width:0;overflow-wrap:anywhere">${esc(x.title)}</span><span class="small mute">${esc(x.newest ? "최근 회차 " + ago(x.newest) : "회차 없음")}</span><span class="pill">${esc(x.episodes)}화</span></div>`));

  return `${stats}
    <h2>구현 기록</h2>${log}
    <h2>Studio 최근 실행</h2>${studio}
    <h2>작품</h2>${workRows}`;
};
