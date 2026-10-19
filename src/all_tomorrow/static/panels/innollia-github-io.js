"use strict";
// innollia.github.io panel (collector: all_tomorrow/project_panels/innollia_site.py). Counts and stats only.
window.AT_PANELS = window.AT_PANELS || {};
window.AT_PANELS["innollia-github-io"] = (panel, project, h) => {
  const { esc, list, ago } = h;
  const num = n => n == null ? "—" : Number(n).toLocaleString("ko-KR");
  const size = b => b == null ? "—" : b >= 1048576 ? (b / 1048576).toFixed(1) + " MB" : b >= 1024 ? Math.round(b / 1024) + " KB" : b + " B";
  const day = s => s ? String(s).slice(0, 10) : "—";
  const card = (label, value, sub = "") => `<div class="card"><div class="mute small">${esc(label)}</div><div class="stat">${esc(value)}</div>${sub ? `<div class="mute small">${esc(sub)}</div>` : ""}</div>`;
  const row = (k, v, extra = "") => `<div><span class="k">${esc(k)}</span><span style="flex:1">${esc(v)}</span>${extra}</div>`;

  const warnings = (panel.warnings || []).map(w => `<div class="card" style="margin-bottom:12px"><span class="dot bad">${esc(w)}</span><div class="small mute" style="margin-top:4px">${esc(panel.chronicle_path || "")} 가 git에 추적되고 있음 (로컬 인덱스 기준)</div></div>`).join("");

  const content = panel.content;
  const sections = content ? Object.entries(content.sections || {}) : [];
  const contentCards = sections.map(([name, n]) => card(name, num(n), "페이지")).join("");

  const c = panel.chronicle;
  let chronicle;
  if (!c) chronicle = `<div class="empty">${esc(panel.chronicle_path || "chronicle 데이터")} 없음</div>`;
  else if (c.error) chronicle = `<div class="empty">chronicle 읽기 실패: ${esc(c.error)}</div>`;
  else chronicle = `<div class="grid">${card("기록", num(c.n), `봉인 ${num(c.sealed)}`)}${card("글자 수", num(c.chars))}${card("이미지", num(c.imgs))}</div>
    <div style="margin-top:12px">${list([
      row("기간", `${day(c.first)} ~ ${day(c.last)}`),
      row("생성", c.gen || "—"),
      row("파일", `${size(c.bytes)} · 수정 ${c.mtime ? ago(c.mtime) : "—"}`),
      row("git 추적", panel.chronicle_tracked == null ? "확인 불가" : panel.chronicle_tracked ? "추적됨" : "추적 안 됨"),
    ])}</div>`;

  return `${warnings}
    <h2>콘텐츠</h2>${content ? `<div class="small mute" style="margin-bottom:8px">content/ 섹션별 마크다운 ${esc(num(content.total))}개 · 섹션 목록(_index.md) 제외${content.truncated ? " · 파일이 많아 일부만 셈" : ""}</div>
      ${contentCards ? `<div class="grid">${contentCards}</div>` : `<div class="empty">섹션 없음</div>`}` : `<div class="empty">content/ 폴더 없음</div>`}
    <h2>Chronicle</h2>${chronicle}`;
};
