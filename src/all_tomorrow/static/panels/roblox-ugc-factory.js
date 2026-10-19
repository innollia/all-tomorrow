"use strict";
// roblox-ugc-factory panel. Data: project_panels/roblox_ugc.py. Every value goes through esc().
(() => {
  const STATE = {
    new: "신규", generated: "생성됨", approved: "승인", preparing: "준비중", validation_passed: "검증 통과",
    ready_to_publish: "게시 준비", published: "게시됨", distributed: "배포됨", rejected: "거절", rerolled: "재생성", failed: "실패",
  };
  const label = s => STATE[s] || s;
  const num = n => (n == null ? "-" : Number(n).toLocaleString("ko-KR"));
  const when = (ago, ts) => (ts ? ago(ts) : "-");
  const bar = pct => `<span style="flex:1;align-self:center"><div class="bar" style="margin-top:0"><i style="width:${Math.max(0, Math.min(100, Math.round(pct)))}%"></i></div></span>`;
  const stat = (k, v, sub) => `<div class="card"><div class="mute small">${k}</div><div class="stat">${v}</div>${sub ? `<div class="mute small">${sub}</div>` : ""}</div>`;

  window.AT_PANELS = window.AT_PANELS || {};
  window.AT_PANELS["roblox-ugc-factory"] = (panel, project, { esc, list, ago }) => {
    const funnel = panel.funnel || [];
    const failed = (funnel.find(r => r.state === "failed") || {}).count || 0;
    const spike = panel.spike;
    const stats = `<div class="grid">${[
      stat("전체 작업", esc(num(panel.jobs_total))),
      stat("검수 대기", esc(num(panel.triage_total))),
      stat("실패", esc(num(failed))),
      stat("최근 스파이크", spike ? esc(spike.date) : "-", spike ? esc(spike.title) : ""),
    ].join("")}</div>`;

    const max = Math.max(1, ...funnel.map(r => r.count || 0));
    const funnelRows = funnel.map(r => `<div><span class="k">${esc(label(r.state))}</span>${bar((r.count || 0) / max * 100)}<span class="mono">${esc(num(r.count))}</span></div>`);

    const triage = panel.triage || [];
    const triageRows = triage.map(t => `<div><span class="k mono">#${esc(t.id)}</span><span class="pill">${esc(t.category)}</span><span style="flex:1">${esc(t.brief)}</span><span class="small mute">${esc(when(ago, t.updated_at))}</span></div>`);
    if ((panel.triage_total || 0) > triage.length) triageRows.push(`<div><span class="mute small">외 ${esc(num(panel.triage_total - triage.length))}건</span></div>`);

    const providerRows = (panel.providers || []).map(p => {
      const total = p.success + p.failed + p.other;
      return `<div><span class="k">${esc(p.provider)}</span><span style="flex:1">성공 ${esc(num(p.success))} · 실패 ${esc(num(p.failed))}${p.other ? ` · 기타 ${esc(num(p.other))}` : ""}</span><span class="mono mute">${total ? Math.round(p.success / total * 100) : 0}%</span></div>`;
    });

    const r = panel.report;
    const verdict = r && r.passed === true ? "통과" : r && r.passed === false ? "실패" : "기록 없음";
    const reportRows = r ? [
      ["작업", `#${r.job} · ${r.file}`], ["삼각형", num(r.triangle_count)], ["정점", num(r.vertex_count)],
      ["판정", verdict], ["작성", when(ago, r.mtime)],
    ].map(([k, v]) => `<div><span class="k">${esc(k)}</span><span>${esc(v)}</span></div>`) : [];

    const eventRows = (panel.events || []).map(e => `<div><span class="k">${esc(when(ago, e.at))}</span><span class="mono">#${esc(e.job_id)}</span><span>${e.from ? esc(label(e.from)) + " → " : ""}${esc(label(e.to))}</span></div>`);

    const problems = panel.problems || [];
    return `${stats}
      ${funnel.length ? `<h2>상태 퍼널</h2>${list(funnelRows)}` : ""}
      <h2>검수 대기열</h2>${list(triageRows)}
      <h2>프로바이더</h2>${list(providerRows)}
      <h2>최근 준비 리포트</h2>${list(reportRows)}
      <h2>최근 이벤트</h2>${list(eventRows)}
      ${problems.length ? `<div class="mute small" style="margin-top:12px">수집 경고: ${problems.map(esc).join(" · ")}</div>` : ""}`;
  };
})();
