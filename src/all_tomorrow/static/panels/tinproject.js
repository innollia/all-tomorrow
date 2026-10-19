// TINProject panel: dryforge cycle, kit status, module STATUS.md, scores and the deletion sentinel.
// Data comes from all_tomorrow.project_panels.tinproject.collect.
(() => {
  window.AT_PANELS = window.AT_PANELS || {};
  window.AT_PANELS["tinproject"] = (panel, project, h) => {
    const { esc, list, ago } = h;
    const when = ts => (ts ? esc(ago(ts)) : "-");
    const pct = v => Math.round(Math.max(0, Math.min(100, Number(v) || 0)));
    const bar = v => `<div class="bar"><i style="width:${pct(v)}%"></i></div>`;
    const badStyle = 'style="border-color:var(--bad);color:var(--bad)"';
    const out = [];

    // Deletion sentinel first: its absence is the one alarm on this page.
    const sentinel = panel.sentinel || {};
    const sync = panel.sync || {};
    const sentinelPill = sentinel.state === "present" ? `<span class="pill dot ok">있음</span>`
      : sentinel.state === "sync_hold" ? `<span class="pill dot PAUSED">동기화 중 — 판단 보류</span>`
      : `<span class="pill dot bad" ${badStyle}>사라짐 — 파일 삭제 의심</span>`;
    if (sentinel.state === "missing") {
      out.push(`<div class="card" style="border-color:var(--bad);margin-bottom:12px">
        <div class="t" style="color:var(--bad)">감시 파일이 사라짐</div>
        <div class="small mute"><span class="mono">${esc(sentinel.path)}</span> 이 없다. 동기화 신호(project.godot 없음, 임시 파일)도 없으므로 이 폴더 주변 파일을 지우는 주체가 있을 수 있다.</div></div>`);
    }
    if (sync.in_progress) {
      out.push(`<div class="card" style="margin-bottom:12px"><span class="pill dot PAUSED">동기화 중</span>
        <span class="small mute">${(sync.reasons || []).map(esc).join(" · ")} — 빠진 파일은 아직 안 왔을 수 있음</span></div>`);
    }

    // Overview cards.
    const df = panel.dryforge;
    const kits = panel.kits || [];
    const mods = panel.modules || [];
    const withStatus = mods.filter(m => m.status_file);
    const pending = kits.reduce((n, k) => n + (Number(k.pending_questions) || 0), 0);
    const score = panel.quote_score;
    const judge = panel.judge_eval;
    const cards = [
      `<div class="card"><div class="t">dryforge 사이클</div><div class="stat">${df ? esc(df.cycles) : "-"}</div>
        <div class="small mono mute">${df && df.branch ? esc(df.branch) : "현재 사이클 없음"}</div></div>`,
      `<div class="card"><div class="t">Kit 상태 파일</div><div class="stat">${esc(kits.length)}</div>
        <div class="small mute">사용자 답 대기 질문 ${esc(pending)}개${(panel.kits_without_status || []).length ? ` · 상태 파일 없는 Kit ${esc(panel.kits_without_status.length)}` : ""}</div></div>`,
      `<div class="card"><div class="t">모듈</div><div class="stat">${esc(mods.length)}</div>
        <div class="small mute">STATUS.md 있음 ${esc(withStatus.length)}개</div></div>`,
      score ? `<div class="card"><div class="t">quote_vn 자동 채점</div>
        <div class="stat">${score.total == null ? "-" : esc(score.total)}<span class="small mute"> / ${esc(score.max ?? "-")}</span></div>
        ${score.total != null && score.max ? bar(score.total / score.max * 100) : ""}
        <div class="small mute" style="margin-top:6px">${(score.parts || []).map(p => `${esc(p.label)} ${esc(p.score)}`).join(" · ")}</div>
        <div class="small mute">${when(score.mtime)}</div></div>`
        : `<div class="card"><div class="t">quote_vn 자동 채점</div><div class="empty">score.md 없음</div></div>`,
      judge ? `<div class="card"><div class="t">분신 판정 일치율</div>
        <div class="small">판정 일치 ${judge.verdict_pct == null ? "-" : esc(judge.verdict_pct) + "%"}</div>${bar(judge.verdict_pct)}
        <div class="small" style="margin-top:6px">이유 일치 ${judge.reason_pct == null ? "-" : esc(judge.reason_pct) + "%"}</div>${bar(judge.reason_pct)}
        <div class="small mute" style="margin-top:6px">${judge.basis ? esc(judge.basis) : "기준 미상"}${judge.first_verdict_pct != null ? ` · 처음 ${esc(judge.first_verdict_pct)}% / ${esc(judge.first_reason_pct ?? "-")}%` : ""}</div>
        <div class="small mute">${when(judge.mtime)}</div></div>`
        : `<div class="card"><div class="t">분신 판정 일치율</div><div class="empty">eval_report.md 없음</div></div>`,
      `<div class="card"><div class="t">삭제 감시 파일</div><div style="margin-top:8px">${sentinelPill}</div>
        <div class="small mono mute" style="margin-top:6px">${esc(sentinel.path || "")}</div></div>`,
    ];
    out.push(`<div class="grid">${cards.join("")}</div>`);

    // dryforge current cycle.
    out.push(`<h2>dryforge 현재 사이클</h2>`);
    out.push(df ? list([
      `<div><span class="k">브랜치</span><span class="mono">${esc(df.branch || "-")}</span></div>`,
      `<div><span class="k">의도</span><span>${esc(df.intent || "-")}</span></div>`,
      `<div><span class="k">사이클 폴더</span><span>${esc(df.cycles)}개${df.latest_cycle ? ` · 최근 ${esc(df.latest_cycle)}` : ""}</span></div>`,
    ]) : `<div class="empty">.dryforge 없음</div>`);

    // Kits.
    const kitName = k => String(k).replace(/_KIT$/i, "").replace(/_/g, " ");
    out.push(`<h2>Kit</h2>`);
    out.push(list([
      ...kits.map(k => `<div><span style="flex:1;min-width:0">${esc(kitName(k.kit))}
        <div class="small mute">갱신 ${esc(k.updated || "-")} · <span class="mono">${esc(k.branch || "브랜치 미기재")}</span></div>
        ${k.answer_note ? `<div class="small mute">상단에 사용자 답 전달 메모 있음 — 표의 대기 상태가 늦게 갱신됐을 수 있음</div>` : ""}</span>
        <span class="pill">${k.pending_questions == null ? "질문 표 없음" : `대기 질문 ${esc(k.pending_questions)}/${esc(k.questions)}`}</span></div>`),
      ...(panel.kits_without_status || []).map(name => `<div><span style="flex:1" class="mute">${esc(kitName(name))}</span><span class="small mute">IMPLEMENTATION_STATUS.md 없음</span></div>`),
    ]));

    // Modules.
    const without = mods.filter(m => !m.status_file);
    out.push(`<h2>모듈</h2>`);
    out.push(list([
      ...withStatus.map(m => `<div><span style="flex:1;min-width:0" class="mono">${esc(m.name)}</span>
        <span class="small">다음 할 일 ${esc(m.next ?? "-")} · 질문 ${esc(m.questions ?? "-")}${m.questions_note ? ` <span class="mute">(${esc(m.questions_note)})</span>` : ""}</span>
        <span class="small mute">${when(m.mtime)}</span></div>`),
      ...(without.length ? [`<div><span class="small mute">STATUS.md 없음 ${esc(without.length)}개: ${without.map(m => esc(m.name)).join(", ")}</span></div>`] : []),
    ]));

    const foot = [`수집 ${esc(panel.collect_ms ?? "-")}ms`];
    if (sync.scanned_entries != null) foot.push(`동기화 탐색 ${esc(sync.scanned_entries)}개 항목${sync.scan_complete ? "" : "(일부)"}`);
    if ((panel.notes || []).length) foot.push(`메모: ${panel.notes.map(esc).join(" · ")}`);
    out.push(`<div class="small mute" style="margin-top:12px">${foot.join(" · ")}</div>`);
    return out.join("");
  };
})();
