"use strict";
// eve-scene-runtime panel (collector: all_tomorrow/project_panels/eve.py). Local copy only; production is on EC2.
window.AT_PANELS = window.AT_PANELS || {};
window.AT_PANELS["eve-scene-runtime"] = (panel, project, h) => {
  const { esc, list, ago } = h;
  const num = n => n == null ? "—" : Number(n).toLocaleString("ko-KR");
  const when = ts => ts ? ago(ts) : "—";
  const ab = (a, b) => a == null || b == null ? "알 수 없음" : `+${a} / −${b}`;
  const size = b => b == null ? "—" : b >= 1048576 ? (b / 1048576).toFixed(1) + " MB" : b >= 1024 ? Math.round(b / 1024) + " KB" : b + " B";
  const bar = pct => `<div class="bar"><i class="${pct >= 80 ? "hi" : ""}" style="width:${Math.max(0, Math.min(Number(pct) || 0, 100))}%"></i></div>`;
  const row = (k, v, extra = "") => `<div><span class="k">${esc(k)}</span><span style="flex:1">${esc(v)}</span>${extra}</div>`;
  const card = (label, value, sub = "", extra = "") => `<div class="card"><div class="mute small">${esc(label)}</div><div class="stat">${esc(value)}</div>${extra}${sub ? `<div class="mute small">${esc(sub)}</div>` : ""}</div>`;

  const st = panel.status || {}, gates = st.gates || [];
  const git = panel.git || {}, audit = panel.audit, ses = panel.session, dbs = panel.sqlite || [];
  const latest = gates[gates.length - 1];
  const passed = gates.filter(g => /^PASS\b/.test(g.result || "")).length;
  const failPct = audit && audit.failure_ratio != null ? Math.round(audit.failure_ratio * 1000) / 10 : null;

  const cards = [
    latest ? card("최신 게이트", `${latest.gate} ${(latest.result || "").split(" ")[0]}`, `${passed}/${gates.length} PASS · ${latest.date || "날짜 없음"}`) : card("최신 게이트", "—", "게이트 목록을 찾지 못함"),
    git.main ? card(`${git.base || "main"} ↔ origin`, ab(git.main.ahead, git.main.behind), `fetch ${when(git.origin_fetched_at)} 기준`) : card("main ↔ origin", "—", "로컬 ref 없음"),
    audit ? card("감사 실패율", failPct == null ? "—" : failPct + "%", `${num(audit.failures)}/${num(audit.total)} · 마지막 ${when(audit.last_event_at)}`) : card("감사 실패율", "—", "감사 로그 없음"),
    ses && !ses.error ? card("세션 대화량", ses.pct == null ? "—" : ses.pct + "%", `${num(ses.chars)} / ${num(ses.threshold)}자 · ${num(ses.turns)}턴`, ses.pct == null ? "" : bar(ses.pct)) : card("세션 대화량", "—", ses && ses.error ? ses.error : "세션 파일 없음"),
  ].join("");

  const gateRows = gates.map(g => `<div><span class="k mono">Gate ${esc(g.gate)}</span><span style="flex:1">${esc(g.name || "")}${g.in_handover ? "" : ` <span class="mute small">HANDOVER 미기재</span>`}${g.handover_result ? ` <span class="mute small">HANDOVER: ${esc(g.handover_result)}</span>` : ""}</span><span class="mono mute small">${esc(g.date || "")}</span><span class="pill">${esc(g.result)}</span></div>`);

  const gitRows = [];
  if (git.main) gitRows.push(row(git.base || "main", `origin/${git.base || "main"} 대비 ${ab(git.main.ahead, git.main.behind)}`, `<span class="small mute">origin 커밋 ${esc(when(git.main.origin_date))}</span>`));
  if (git.desktop) gitRows.push(row("desktop", `${git.desktop.newest} · ${when(git.desktop.date)} · main 대비 ${ab(git.desktop.ahead, git.desktop.behind)}`, `<span class="small mute">브랜치 ${esc(num(git.desktop.count))}개</span>`));
  if (git.edge) {
    const wt = git.edge.worktree;
    const where = wt ? `워크트리 ${wt.name}${wt.missing ? " (폴더 없음)" : ""}` : "워크트리 없음";
    const merged = git.edge.merged == null ? "판정 불가" : git.edge.merged ? "main에 포함" : "미병합";
    gitRows.push(row("edge", `${git.edge.branch} · ${where} · ${when(git.edge.date)} · main 대비 ${ab(git.edge.ahead, git.edge.behind)}`, `<span class="pill">${esc(merged)}</span>`));
  }

  const eventRows = audit ? audit.events.map(e => `<div><span style="flex:1" class="mono">${esc(e.event)}</span>${e.failed ? `<span class="dot bad small">실패 ${esc(num(e.failed))}</span>` : ""}<span class="mono">${esc(num(e.count))}</span></div>`) : [];
  if (audit && audit.other_events) eventRows.push(row("기타", `${num(audit.other_events)}건`));
  const auditNote = audit ? [
    `총 ${num(audit.total)}건`, `마지막 이벤트 ${when(audit.last_event_at)}`, `마지막 실패 ${when(audit.last_failure_at)}`,
    audit.truncated ? `파일 끝 ${size(audit.file_bytes)} 중 일부만 집계` : "", audit.bad_lines ? `깨진 줄 ${num(audit.bad_lines)}` : "",
  ].filter(Boolean).join(" · ") : "";

  const sessionRows = ses && !ses.error ? [
    `<div><span class="k">대화량</span><span style="flex:1">${esc(num(ses.chars))} / ${esc(num(ses.threshold))}자${ses.pct == null ? "" : bar(ses.pct)}</span><span class="mono mute">${esc(ses.pct == null ? "—" : ses.pct + "%")}</span></div>`,
    row("턴 수", num(ses.turns)),
    row("롤오버", ses.rollover_status || "—"),
    `<div><span class="k">문서 갱신</span><span style="flex:1">${ses.doc_refresh_ok == null ? "—" : `<span class="dot ${ses.doc_refresh_ok ? "ok" : "bad"}">${ses.doc_refresh_ok ? "성공" : "실패"}</span>`}</span><span class="small mute">${esc(when(ses.doc_refresh_at))}</span></div>`,
    row("저장", when(ses.saved_at)),
  ] : [];

  const dbRows = dbs.map(d => `<div><span style="flex:1" class="mono">${esc(d.name)}</span><span class="mono mute">${esc(size(d.bytes))}${d.wal_bytes ? ` + WAL ${esc(size(d.wal_bytes))}` : ""}</span><span class="small mute">${esc(when(d.mtime))}</span></div>`);

  return `<div class="small mute" style="margin-bottom:12px">이 PC의 로컬 사본 기준 · 운영 상태(Discord 봇, MCP 서버, Notion 릴레이)는 EC2에 있음</div>
    <div class="grid">${cards}</div>
    <h2>게이트</h2>${st.handover_status ? `<div class="mono small mute" style="margin-bottom:8px">${esc(st.handover_status)}</div>` : ""}${list(gateRows)}
    <h2>Git (로컬 ref, fetch 안 함)</h2>${panel.git ? list(gitRows) : `<div class="empty">git 저장소 아님</div>`}
    <h2>Discord 감사 로그</h2>${audit ? `<div class="small mute" style="margin-bottom:8px">${esc(auditNote)}</div>${list(eventRows)}` : `<div class="empty">data/discord-audit.jsonl 없음</div>`}
    <h2>매니저 세션</h2>${ses ? (ses.error ? `<div class="empty">세션 파일 읽기 실패: ${esc(ses.error)}</div>` : list(sessionRows)) : `<div class="empty">data/manager-session-state.json 없음</div>`}
    <h2>SQLite 파일</h2>${list(dbRows)}`;
};
