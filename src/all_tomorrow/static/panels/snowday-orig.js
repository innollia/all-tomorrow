// Snow Day prototype panel: TODO counts, GameMaker build results, dialogue preview presence.
// Data comes from all_tomorrow.project_panels.snowday.collect.
(() => {
  window.AT_PANELS = window.AT_PANELS || {};
  window.AT_PANELS["snowday-orig"] = (panel, project, h) => {
    const { esc, list, ago } = h;
    const when = ts => (ts ? esc(ago(ts)) : "-");
    const pct = v => Math.round(Math.max(0, Math.min(100, Number(v) || 0)));
    const RESULT = { success: ["성공", "ok"], fail: ["실패", "bad"], incomplete: ["끝 표식 없음", "PAUSED"], unreadable: ["읽기 실패", ""] };
    const result = b => { const [label, cls] = RESULT[b.result] || [String(b.result), ""]; return `<span class="pill dot ${cls}">${esc(label)}</span>`; };
    const out = [];

    const todo = panel.todo;
    const build = panel.latest_build;
    const preview = panel.dialogue_preview || {};
    const cards = [
      todo ? `<div class="card"><div class="t">TODO</div>
        <div class="stat">${esc(todo.done)}<span class="small mute"> / ${esc(todo.total)} 완료</span></div>
        <div class="bar"><i style="width:${todo.total ? pct(todo.done / todo.total * 100) : 0}%"></i></div>
        <div class="small mute" style="margin-top:6px">진행 중 ${esc(todo.in_progress)} · 미착수 ${esc(todo.todo)}${todo.other ? ` · 기타 ${esc(todo.other)}` : ""}</div>
        <div class="small mute">${when(todo.mtime)}</div></div>`
        : `<div class="card"><div class="t">TODO</div><div class="empty">TODO.txt 없음</div></div>`,
      build ? `<div class="card"><div class="t">최근 빌드</div><div style="margin-top:8px">${result(build)}</div>
        <div class="small mono mute" style="margin-top:6px">${esc(build.name)} · ${when(build.mtime)}</div>
        ${panel.latest_ambiguous ? `<div class="small mute">로그 파일 시각이 거의 같음 — 동기화 복사 시각이라 '최근'이 불확실</div>` : ""}</div>`
        : `<div class="card"><div class="t">최근 빌드</div><div class="empty">빌드 로그 없음</div></div>`,
      `<div class="card"><div class="t">대화 미리보기</div><div class="stat">${preview.exists ? "있음" : "없음"}</div>
        <div class="small mono mute">dialogue-preview/index.html${preview.exists ? ` · ${when(preview.mtime)}` : ""}</div></div>`,
    ];
    out.push(`<div class="grid">${cards.join("")}</div>`);

    out.push(`<h2>빌드 로그</h2>`);
    out.push(list((panel.builds || []).map(b => {
      const detail = [
        b.exit_code != null ? `종료 코드 ${esc(b.exit_code)}` : "",
        b.errors ? `Error ${esc(b.errors)}건${b.first_error ? `: ${esc(b.first_error)}` : ""}` : "",
        b.last_step ? `마지막 단계: ${esc(b.last_step)}` : "",
      ].filter(Boolean);
      return `<div><span style="flex:1;min-width:0"><span class="mono">${esc(b.name)}</span>
        ${detail.length ? `<div class="small mute">${detail.join(" · ")}</div>` : ""}</span>
        ${result(b)}<span class="small mute">${when(b.mtime)}</span></div>`;
    })));

    const foot = [`수집 ${esc(panel.collect_ms ?? "-")}ms`];
    if ((panel.notes || []).length) foot.push(`메모: ${panel.notes.map(esc).join(" · ")}`);
    out.push(`<div class="small mute" style="margin-top:12px">${foot.join(" · ")}</div>`);
    return out.join("");
  };
})();
