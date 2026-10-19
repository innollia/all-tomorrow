"use strict";
// survey-copilot panel. Data: project_panels/survey_copilot.py. Every value goes through esc().
(() => {
  const STATUS = { new: "신규", opened: "열람", screened_out: "스크리닝 탈락", completed: "완료", approved: "승인", rejected: "거절", skipped: "건너뜀" };
  const KIND = { earned: "적립", approved: "승인", paid: "지급" };
  const num = n => (n == null ? "-" : Number(n).toLocaleString("ko-KR"));
  const won = n => "₩" + num(n);
  const bar = pct => `<span style="flex:1;align-self:center"><div class="bar" style="margin-top:0"><i style="width:${Math.max(0, Math.min(100, Math.round(pct)))}%"></i></div></span>`;
  const stat = (k, v) => `<div class="card"><div class="mute small">${k}</div><div class="stat">${v}</div></div>`;

  window.AT_PANELS = window.AT_PANELS || {};
  window.AT_PANELS["survey-copilot"] = (panel, project, { esc, list, ago }) => {
    const bridge = panel.bridge;
    const bridgeRows = bridge ? [`<div><span class="k">미응답</span><span style="flex:1">${esc(num(bridge.pending))} / 전체 ${esc(num(bridge.requests))}</span><span class="small mute">${bridge.oldest_pending_at ? "가장 오래된 요청 " + esc(ago(bridge.oldest_pending_at)) : ""}</span></div>`] : [];
    const bridgeHtml = `<h2>브리지 요청</h2>${bridge ? list(bridgeRows) : `<div class="empty">bridge/inbox 없음</div>`}`;
    const note = panel.note ? `<div class="empty">${esc(panel.note)}</div>` : "";
    const problems = (panel.problems || []).length ? `<div class="mute small" style="margin-top:12px">수집 경고: ${panel.problems.map(esc).join(" · ")}</div>` : "";
    if (!panel.db) return note + bridgeHtml + problems;

    const statuses = panel.statuses || [];
    const count = s => (statuses.find(r => r.status === s) || {}).count || 0;
    const ledger = panel.ledger || {};
    const stats = `<div class="grid">${[
      stat("신규 오퍼", esc(num(count("new")))),
      stat("브리지 대기", esc(bridge ? num(bridge.pending) : "-")),
      stat("30일 승인액", esc(ledger.approved ? won(ledger.approved.d30_krw) : "-")),
      stat("누적 지급액", esc(ledger.paid ? won(ledger.paid.all_krw) : "-")),
    ].join("")}</div>`;

    const max = Math.max(1, ...statuses.map(r => r.count || 0));
    const statusRows = statuses.map(r => `<div><span class="k">${esc(STATUS[r.status] || r.status)}</span>${bar((r.count || 0) / max * 100)}<span class="mono">${esc(num(r.count))}</span></div>`);
    const dup = panel.duplicates ? `<div class="mute small" style="margin-top:6px">중복으로 묶인 오퍼 ${esc(num(panel.duplicates))}건은 제외</div>` : "";

    const topRows = (panel.top_new || []).map(o => `<div><span class="k mono">${esc(num(o.krw_per_min))}원/분</span><span style="flex:1">${esc(o.platform)}</span><span class="small mute">${esc(won(o.reward_krw))} · ${esc(num(o.minutes))}분 · 통과 ${esc(Math.round(o.p_qualify * 100))}% · 마감 ${esc(o.deadline || "-")}</span></div>`);
    const unscored = panel.unscored_new ? `<div class="mute small" style="margin-top:6px">보상·소요시간·통과확률이 비어 제외된 신규 오퍼 ${esc(num(panel.unscored_new))}건</div>` : "";

    const ledgerRows = Object.keys(KIND).filter(k => ledger[k]).map(k => `<div><span class="k">${KIND[k]}</span><span style="flex:1">전체 ${esc(won(ledger[k].all_krw))} <span class="small mute">(${esc(num(ledger[k].entries))}건)</span></span><span class="small mute">30일 ${esc(won(ledger[k].d30_krw))}</span></div>`);

    return `${note}${stats}
      ${statuses.length ? `<h2>오퍼 상태</h2>${list(statusRows)}${dup}` : ""}
      ${statuses.length ? `<h2>기대값 상위 신규 오퍼</h2><div class="mute small" style="margin-bottom:6px">보상 × 통과확률 ÷ 소요분</div>${list(topRows)}${unscored}` : ""}
      ${panel.ledger ? `<h2>원장</h2>${list(ledgerRows)}` : ""}
      ${bridgeHtml}${problems}`;
  };
})();
