"use strict";
// 조사 목록: 놀 때 Codex가 조사할 주제를 사용자가 정해 둔다. 위에 있는 주제가 먼저 돈다.
// API: /api/research/* (console/research.py). 실행기: overseer/idle_research.py(PC 미사용 10분, Codex 잔량 80% 미만).
(() => {
  const { $, view, esc, api, toast, ago, list } = AT;
  AT.nav.push({ section: "기획", label: "조사 목록", href: "#/research", order: 40 });
  AT.navAlias = Object.assign(AT.navAlias || {}, { "/research-run": "/research" });
  const STATUS = { RUNNING: "도는 중", SUCCESS: "끝", FAILED: "실패", INTERRUPTED: "끊김", LOST: "잃어버림" };
  const repeatText = d => d > 0 ? `${d}일마다` : "한 번";
  let topics = [];

  const runLine = r => `<div class="row small" style="gap:8px"><span class="dot ${r.status === "SUCCESS" ? "ok" : r.status === "RUNNING" ? "" : "bad"}">${esc(STATUS[r.status] || r.status)}</span>`
    + `<span class="mute">${ago(new Date(r.started * 1000))}</span>`
    + (r.result_file ? `<a href="#/research-run/${encodeURIComponent(r.id)}">결과 보기</a>` : r.error ? `<span class="mute">${esc(r.error.slice(0, 80))}</span>` : "") + `</div>`;

  const card = (t, i) => `<div class="card" data-topic="${esc(t.id)}">
    <div class="row" style="justify-content:space-between;gap:8px"><span class="t">${esc(t.title)}</span>
      <span class="mute small">${esc(t.project_id)} · ${repeatText(t.repeat_days)}${t.enabled ? "" : " · 꺼짐"}</span></div>
    <div class="small" style="white-space:pre-wrap;margin:6px 0">${esc(t.ask)}</div>
    ${t.runs.map(runLine).join("")}
    <div class="row" style="gap:6px;margin-top:8px;flex-wrap:wrap">
      <button data-act="now">지금 돌리기</button>
      <button data-act="toggle">${t.enabled ? "끄기" : "켜기"}</button>
      <button data-act="up" ${i === 0 ? "disabled" : ""}>위로</button>
      <button data-act="down" ${i === topics.length - 1 ? "disabled" : ""}>아래로</button>
      <button data-act="edit">고치기</button>
      <button data-act="del">삭제</button>
    </div></div>`;

  AT.pages["/research"] = async () => {
    topics = await api("/api/research");
    return `<h1>조사 목록</h1>
      <div class="sub">PC를 10분 넘게 안 쓰고 Codex 잔량이 남으면 위에서부터 하나씩 조사합니다. '지금 돌리기'는 PC 사용 중에도 다음 1분 안에 시작합니다.</div>
      <form id="research-new" class="card">
        <input id="rs-title" placeholder="제목(비우면 요청 첫 줄)" style="width:100%">
        <textarea id="rs-ask" rows="4" placeholder="무엇을 조사할지. 예: 한국 인디 게임 개발자 커뮤니티에서 요즘 자주 나오는 AI 도구 불만" style="width:100%;margin-top:6px"></textarea>
        <div class="row" style="gap:8px;margin-top:6px;flex-wrap:wrap">
          <label class="small">프로젝트 <input id="rs-project" value="all-tomorrow" size="14"></label>
          <label class="small">반복 <input id="rs-repeat" type="number" min="0" step="1" value="0" style="width:60px">일(0은 한 번)</label>
          <button type="submit">추가</button>
        </div>
      </form>
      ${list(topics.map(card))}`;
  };
  AT.refresh["/research"] = 60000;

  AT.pages["/research-run/"] = async id => {
    const r = await api(`/api/research/runs/${encodeURIComponent(id)}`);
    return `<div class="row" style="justify-content:space-between"><h1>${esc(r.title)}</h1><a href="#/research">목록</a></div>
      <div class="sub">${new Date(r.started * 1000).toLocaleString()} · ${esc(r.project_id)}</div>
      <div class="card" style="white-space:pre-wrap">${esc(r.text)}</div>`;
  };

  view.addEventListener("submit", async e => {
    if (e.target.id !== "research-new") return;
    e.preventDefault();
    const ask = $("#rs-ask").value.trim(); if (!ask) return;
    try {
      await api("/api/research", { title: $("#rs-title").value, ask, project_id: $("#rs-project").value.trim() || "all-tomorrow", repeat_days: Number($("#rs-repeat").value) || 0 });
      toast("추가함"); AT.render();
    } catch (err) { toast("실패: " + err.message); }
  });
  view.addEventListener("click", async e => {
    const b = e.target.closest("button[data-act]"); const box = b && b.closest("[data-topic]");
    if (!box || !view.contains(b)) return;
    const t = topics.find(x => x.id === box.dataset.topic); if (!t) return;
    const url = `/api/research/${encodeURIComponent(t.id)}`;
    try {
      const act = b.dataset.act;
      if (act === "now") { await api(url, { run_now: true }, "PUT"); toast("다음 점검에서 시작"); }
      else if (act === "toggle") await api(url, { enabled: !t.enabled }, "PUT");
      else if (act === "up" || act === "down") await api(url, { move: act === "up" ? -1 : 1 }, "PUT");
      else if (act === "edit") {
        const ask = prompt("조사할 내용", t.ask); if (ask === null || !ask.trim()) return;
        const repeat = prompt("반복 주기(일, 0은 한 번)", String(t.repeat_days)); if (repeat === null) return;
        await api(url, { ask, repeat_days: Number(repeat) || 0 }, "PUT");
      } else if (act === "del") {
        if (!confirm(`"${t.title}"을(를) 목록에서 지운다. 지난 결과 파일은 남는다.`)) return;
        await api(url, undefined, "DELETE");
      }
      AT.render();
    } catch (err) { toast("실패: " + err.message); }
  });
})();
