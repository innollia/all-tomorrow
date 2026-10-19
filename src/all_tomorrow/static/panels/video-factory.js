"use strict";
// video-factory panel: episode stages, QA and board approvals. Data from project_panels/video_factory.py.
window.AT_PANELS = window.AT_PANELS || {};
window.AT_PANELS["video-factory"] = (panel, project, h) => {
  const { esc, list, ago } = h;
  const STAGE = { brief: "기획", facts: "사실표", script: "대본", shots: "화면 계획", timeline: "내레이션", review: "검수", output: "완성본", youtube: "게시 준비" };
  const stat = (label, value, note) => `<div class="card"><div class="mute small">${esc(label)}</div><div class="stat">${esc(value ?? "-")}</div>${note ? `<div class="mute small">${esc(note)}</div>` : ""}</div>`;
  const eps = panel.episodes || [];
  const board = panel.board || {};
  const rr = panel.review_render || {};

  const qaText = q => {
    if (!q) return "검수 폴더 없음";
    const parts = [];
    if (q.defects != null) parts.push(`결함 ${q.defects}`);
    if (q.warnings != null) parts.push(`주의 ${q.warnings}`);
    if (q.verdict_fail != null) parts.push(q.verdict_fail ? `판정 실패 ${q.verdict_fail}` : `판정 통과 ${q.verdict_pass}`);
    if (q.unchecked) parts.push(`미체크 ${q.unchecked}`);
    if (q.remaining) parts.push(`남은 메모 ${q.remaining}`);
    return parts.length ? parts.join(" · ") : "사전 검사·판정 기록 없음";
  };
  const boardText = b => b ? ` · 보드 승인 ${b.ok} 수정 ${b.fix}` : "";

  const openTotal = eps.reduce((n, e) => n + ((e.qa && e.qa.open) || 0), 0);
  const stats = `<div class="grid">${[
    stat("에피소드", eps.length + (panel.more || 0)),
    stat("완성본", eps.filter(e => e.final).length),
    stat("열린 QA", openTotal, "결함 + 판정 실패 + 남은 항목"),
    stat("보드 수정 요청", board.fix ?? 0, `승인 ${board.ok ?? 0}`),
  ].join("")}</div>`;

  const rows = eps.map(e => {
    const pct = e.stage_total ? Math.round(100 * e.stage_index / e.stage_total) : 0;
    const skipped = (e.skipped || []).length ? ` · 건너뜀 ${e.skipped.map(k => STAGE[k] || k).join(", ")}` : "";
    return `<div><span style="flex:1">${e.title ? `${esc(e.title)} <span class="mono mute">${esc(e.id)}</span>` : `<span class="mono">${esc(e.id)}</span>`}
      <div class="bar"><i style="width:${pct}%"></i></div>
      <div class="small mute">${esc(qaText(e.qa) + boardText(e.board) + skipped)}</div></span>
      <span class="small mute">${esc(e.final ? "완성본 " + ago(e.final_at) : "완성본 없음")}</span>
      <span class="pill">${esc(e.stage ? (STAGE[e.stage] || e.stage) : "시작 전")}</span></div>`;
  });

  const render = [
    `<div><span class="k">검토본</span><span style="flex:1">${esc(rr.video || "없음")}</span><span class="small mute">${esc(rr.video_at ? ago(rr.video_at) : "-")}</span></div>`,
    `<div><span class="k">렌더 로그</span><span style="flex:1">render-review.log</span><span class="small mute">${esc(rr.log_at ? ago(rr.log_at) : "없음")}</span></div>`,
  ];

  return `${stats}
    <h2>에피소드</h2>${list(rows)}
    <h2>최근 검토 렌더</h2>${list(render)}`;
};
