"use strict";
// Memory: what holds this PC's memory, grouped by session / MCP / All Tomorrow / app. A view to open, never a warning.
(() => {
  const { esc, api } = AT;
  AT.nav.push({ section: "모니터링", label: "메모리", href: "#/memory", order: 62 });
  const gb = v => `${v.toFixed(v < 10 ? 2 : 1)} GB`;
  const idle = m => m == null ? "-" : m < 1 ? "방금" : m < 60 ? `${m}분 전` : m < 1440 ? `${Math.round(m / 60)}시간 전` : `${Math.round(m / 1440)}일 전`;
  const share = (v, total) => `<div class="bar"><i style="width:${total ? Math.min(100, v / total * 100) : 0}%"></i></div>`;
  const table = (head, rows, empty) => rows.length
    ? `<div class="memory-table" role="region" tabindex="0"><table><thead><tr>${head.map(h => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`
    : `<div class="empty">${empty}</div>`;

  AT.pages["/memory"] = async () => {
    const d = await api("/api/memory");
    if (!d.available) return `<h1>메모리</h1><div class="empty">${esc(d.reason)}</div>`;
    const t = d.totals;
    const top = Math.max(...d.sessions.map(s => s.gb), 0.01);
    const summary = d.summary.map(g => `<div class="card"><div class="mute small">${esc(g.label)}</div><div class="stat">${gb(g.gb)}</div><div class="mute small">${g.count}개</div></div>`).join("");
    const sessions = d.sessions.map(s => `<tr>
      <td><div>${esc(s.title)}${s.archived ? ' <span class="pill">보관됨</span>' : ""}</div><div class="mute small">${esc(s.folder)}</div></td>
      <td class="mono small">${idle(s.idle_minutes)}</td>
      <td class="mono">${gb(s.gb)}${share(s.gb, top)}</td>
      <td class="small mute">${s.parts.map(p => `${esc(p.label)} ${p.gb.toFixed(2)}`).join(" · ")}</td></tr>`);
    const mcp = d.mcp.map(m => `<tr><td>${esc(m.label)}</td><td class="mono">${m.count}</td><td class="mono">${gb(m.gb)}</td><td class="mono small mute">${(m.gb / m.count * 1024).toFixed(0)} MB</td></tr>`);
    const at = d.all_tomorrow.map(a => `<tr><td>${esc(a.label)}</td><td class="mono">${gb(a.gb)}</td></tr>`);
    const apps = d.apps.map(a => `<tr><td>${esc(a.label)}</td><td class="mono">${a.count || "-"}</td><td class="mono">${gb(a.gb)}</td></tr>`);
    return `<section class="memory"><h1>메모리</h1>
      <div class="sub">${t ? `실메모리 ${t.physical_used_gb}/${t.physical_gb} GB · 커밋 ${t.commit_gb}/${t.commit_limit_gb} GB · ` : ""}프로세스 ${d.process_count}개 · ${new Date(d.observed_at).toLocaleTimeString("ko-KR")} 관측, ${d.cache_seconds}초마다 갱신</div>
      <div class="grid">${summary}</div>
      <h2>Claude Code 세션 <span class="mute">${d.sessions.length}</span></h2>
      <div class="mute small">세션마다 본체와 그 세션이 띄운 MCP 서버를 묶었습니다. 마지막 활동은 그 세션에서 마지막으로 대화가 오간 때입니다.</div>
      ${table(["세션", "마지막 활동", "메모리", "구성 (GB)"], sessions, "떠 있는 세션 없음")}
      <h2>MCP 서버 <span class="mute">세션 합계</span></h2>
      ${table(["MCP", "붙은 세션", "합계", "세션당"], mcp, "MCP 없음")}
      <h2>All Tomorrow</h2>
      ${table(["구성 요소", "메모리"], at, "떠 있는 구성 요소 없음")}
      <h2>그 밖의 앱</h2>
      ${table(["앱", "프로세스", "메모리"], apps, "없음")}
      <div class="mute small memory-note">메모리는 각 프로세스가 확보한 전용 메모리(커밋)입니다. 작업 관리자의 ‘메모리’ 열(실메모리에 올라온 부분)보다 클 수 있습니다.</div>
    </section>`;
  };
  AT.refresh["/memory"] = 30000;
})();
