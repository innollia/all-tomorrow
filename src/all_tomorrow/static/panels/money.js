"use strict";
// money panel: task table and real-world counters from 진행현황.csv. Data from project_panels/money.py.
window.AT_PANELS = window.AT_PANELS || {};
window.AT_PANELS["money"] = (panel, project, h) => {
  const { esc, list, ago } = h;
  const pr = panel.progress;
  const totals = (pr && pr.totals) || {};
  const counter = (label, t) => `<div class="card"><div class="mute small">${esc(label)}</div><div class="stat">${esc(t ? t.sum : "-")}</div>${t && t.unknown ? `<div class="mute small">미확인 ${esc(t.unknown)}건</div>` : ""}</div>`;

  const stats = `<div class="grid">${[
    counter("실제 지원", totals.applied),
    counter("실제 판매", totals.sold),
    counter("현금 수령 검증", totals.cash_verified),
  ].join("")}</div>`;

  const r = panel.report, s = panel.standard;
  const facts = list([
    `<div><span class="k">기준일</span><span>${esc(panel.base_date || "README에 없음")}</span></div>`,
    `<div><span class="k">실행기준</span><span style="flex:1">${esc(s ? s.version : "없음")}${s ? ` <span class="mute small">· ${esc(s.name)}</span>` : ""}</span>${s && s.at ? `<span class="small mute">${esc(ago(s.at))}</span>` : ""}</div>`,
    `<div><span class="k">최신 보고서</span><span style="flex:1">${esc(r ? r.name : "없음")}${r ? ` <span class="mute small">· 전체 ${esc(r.count)}개</span>` : ""}</span>${r && r.at ? `<span class="small mute">${esc(ago(r.at))}</span>` : ""}</div>`,
  ]);

  const tasks = !pr ? `<div class="empty">진행현황.csv 없음</div>`
    : pr.error ? `<div class="empty">진행현황.csv 읽기 실패: ${esc(pr.error)}</div>`
    : !(pr.tasks || []).length ? `<div class="empty">작업 없음</div>`
    : `<table><thead><tr><th>ID</th><th>작업명</th><th>상태</th><th>다음 행동</th></tr></thead><tbody>${pr.tasks.map(t =>
      `<tr><td class="mono">${esc(t.id)}</td><td>${esc(t.name)}</td><td><span class="pill">${esc(String(t.status || "-").replace(/_/g, " "))}</span></td><td class="small">${esc(t.next || "-")}</td></tr>`).join("")}</tbody></table>`;

  return `${stats}<h2>기준</h2>${facts}<h2>작업</h2>${tasks}`;
};
