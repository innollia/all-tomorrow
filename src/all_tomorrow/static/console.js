"use strict";
const $ = (s, el = document) => el.querySelector(s);
const view = $("#view");
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => "&#" + c.charCodeAt(0) + ";");
const STANCE = { support: "지지", oppose: "반대", conditional: "조건부" };
const IDEA = { GENERATED: "생성", KILLED: "폐기", HELD: "보류", IN_COUNCIL: "회의중", REJECTED: "회의 탈락", PROPOSED: "기획안" };
const PSTAT = { PENDING: "대기", APPROVED: "승인", REJECTED: "거부" };
const VERDICT = { EVALUATING: "평가중", KEEP: "유지", PROMOTE: "승진 대상", RETIRE: "퇴출 대상", RETIRED: "퇴출" };
let timer = null;

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  if (r.status === 401) { location = "/login"; throw new Error("auth"); }
  if (!r.ok) { const t = await r.text(); throw new Error(r.status + " " + t.slice(0, 200)); }
  return r.status === 204 ? null : r.json();
}
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.style.display = "block"; clearTimeout(t._h); t._h = setTimeout(() => t.style.display = "none", 3000); }
function ago(ts) { const m = Math.round((Date.now() - new Date(ts)) / 60000); return m < 1 ? "방금" : m < 60 ? m + "분 전" : m < 1440 ? Math.round(m / 60) + "시간 전" : Math.round(m / 1440) + "일 전"; }
function left(t) { const ms = new Date(t) - Date.now(); if (!(ms > 0)) return null; const m = Math.floor(ms / 60000), d = Math.floor(m / 1440), h = Math.floor(m % 1440 / 60); return d ? `${d}일 ${h}시간` : h ? `${h}시간 ${m % 60}분` : `${m % 60}분`; }
const list = items => items.length ? `<div class="list">${items.join("")}</div>` : `<div class="empty">없음</div>`;

// ---------------------------------------------------------------- pages
const pages = {
  async "/"() {
    const [s, usage] = await Promise.all([api("/api/factory/state").catch(() => null), api("/api/usage").catch(() => null)]);
    const usageRows = (usage?.providers || []).map(p => p.windows.map(w => {
      const l = left(w.resets_at); const pct = l === null ? 0 : Math.round(w.percent);
      return `<div><span class="k">${esc(p.name)}</span><span style="flex:1">${esc(w.label)}<div class="bar"><i class="${pct >= 80 ? "hi" : ""}" style="width:${Math.min(pct, 100)}%"></i></div></span><span class="mono mute">${pct}%</span></div>`;
    }).join("")).join("");
    return `<h1>홈</h1><div class="sub">지금 상태 요약</div>
      ${s ? `<div class="grid">
        <a class="card" href="#/autonomy"><div class="mute small">루프</div><div class="stat dot ${s.loop}">${s.loop}</div></a>
        <a class="card" href="#/proposals"><div class="mute small">대기 기획안</div><div class="stat">${s.counts.PENDING}</div></a>
        <a class="card" href="#/autonomy"><div class="mute small">진행 중 주제</div><div class="stat">${s.topics.filter(t => t.status === "RUNNING").length}</div></a>
        <a class="card" href="#/staff"><div class="mute small">재직 직원</div><div class="stat">${s.staff.length}</div></a>
      </div>` : `<div class="empty">아이디어 공장이 이 서버에 연결되지 않음</div>`}
      <h2>구독 사용량</h2>${usageRows ? `<div class="list">${usageRows}</div>` : `<div class="empty">사용량 데이터 없음</div>`}`;
  },

  async "/usage"() {
    const snap = await api("/api/usage");
    if (!snap) return `<h1>구독 사용량</h1><div class="empty">데이터 없음. 로컬 PC에서 all-tomorrow-usage push 실행 필요</div>`;
    const cards = snap.providers.map(p => {
      const ok = p.status === "connected";
      const rows = p.windows.map(w => {
        const l = left(w.resets_at); const pct = l === null ? 0 : Math.round(w.percent);
        return `<div style="padding:8px 0"><div class="row" style="justify-content:space-between"><span>${esc(w.label)}</span><span class="mono mute">${pct}% · ${l === null ? "초기화됨" : l + " 후 초기화"}</span></div><div class="bar"><i class="${pct >= 80 ? "hi" : ""}" style="width:${Math.min(pct, 100)}%"></i></div></div>`;
      }).join("");
      const age = Math.round((Date.now() - new Date(p.observed_at)) / 60000);
      return `<div class="card"><div class="row" style="justify-content:space-between"><span><span class="t">${esc(p.name)}</span> <span class="mute small">${esc(p.plan)}</span></span><span class="dot ${ok ? "ok" : "bad"} small">${ok ? "연결됨" : esc(p.status)}</span></div>${rows || `<div class="empty">데이터 없음</div>`}${age > 30 ? `<div class="mute small">${ago(p.observed_at)} 관측값</div>` : ""}</div>`;
    }).join("");
    return `<h1>구독 사용량</h1><div class="sub">수집 ${ago(snap.collected_at)}</div><div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(300px,1fr))">${cards}</div>`;
  },

  async "/autonomy"() {
    const [s, events] = await Promise.all([api("/api/factory/state"), api("/api/factory/events?limit=60")]);
    const staff = s.staff.map(m => `<div class="card"><div class="t">${esc(m.name)}</div><div class="mono mute">${esc(m.model_group)} · ${m.generation}세대</div><div class="small" style="margin-top:8px">${esc(m.last) || '<span class="mute">발언 없음</span>'}</div></div>`).join("");
    const topics = s.topics.map(t => `<div><span class="k">${ago(t.created_at)}</span><a href="#/topic/${t.id}" style="flex:1">${esc(t.text)}</a><span class="small mute">${Object.entries(t.idea_counts).map(([k, v]) => `${IDEA[k] || k} ${v}`).join(" · ")}</span><span class="pill">${esc(t.status)}</span></div>`);
    const log = events.map(e => `<div><span class="k mono">${e.ts.slice(11, 19)}</span><span class="pill">${esc(e.kind)}</span><span>${esc(e.text)}</span></div>`);
    const can = s.loop !== "KILLED";
    return `<h1>통제면</h1><div class="sub">루프 상태와 직원 발언 · 5초마다 갱신</div>
      <div class="row"><span class="dot ${s.loop}">${s.loop}</span>
        <button data-act="pause" ${s.loop !== "RUN" ? "disabled" : ""}>일시정지</button>
        <button data-act="resume" ${s.loop !== "PAUSED" ? "disabled" : ""}>재개</button>
        <button class="danger" data-act="kill" ${!can ? "disabled" : ""}>KILL</button>
        <button data-act="reset" ${can ? "disabled" : ""}>해제</button>
        <span class="mute small">기획안 누적 ${s.proposed_total}</span></div>
      <h2>주제 던지기</h2>
      ${s.runtime ? `<form id="topicform" class="row"><input id="topictext" placeholder="예: TRPG 유틸리티" style="flex:1;min-width:200px" ${can ? "" : "disabled"}><button class="primary" ${can ? "" : "disabled"}>시작</button></form>`
        : `<div class="mute small">이 서버 프로세스에는 실행기가 없어 주제를 시작할 수 없음</div>`}
      <h2>직원</h2><div class="grid">${staff}</div>
      <h2>주제</h2>${list(topics)}
      <h2>이벤트</h2>${list(log)}`;
  },

  async "/topic"(id) {
    const t = await api("/api/factory/topics/" + id);
    const ideas = t.ideas.slice().sort((a, b) => a.idx - b.idx).map(i => `<div class="card" style="margin-bottom:10px">
      <div class="row" style="justify-content:space-between"><span class="t">${esc(i.title)}</span><span class="pill">${IDEA[i.status] || i.status}</span></div>
      <div class="small" style="margin-top:6px">${esc(i.problem)}</div><div class="small mute">${esc(i.approach)}</div>
      ${i.verdict_reason ? `<div class="small" style="margin-top:6px"><span class="mute">신서사이저:</span> ${esc(i.verdict_reason)}</div>` : ""}
      ${i.evidence.map(e => `<div class="small"><a class="mono" href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.number)}</a> ${esc(e.title)} — <span class="mute">${esc(e.element)}</span></div>`).join("")}
      ${i.votes.length ? `<details><summary>회의 ${i.votes.length}건</summary>${i.votes.map(v => `<div class="small" style="margin-top:6px"><b>${v.round}R ${esc(v.staff_id)}</b> ${STANCE[v.stance] || v.stance} — ${esc(v.reason)}</div>`).join("")}</details>` : ""}
    </div>`).join("");
    return `<h1>${esc(t.text)}</h1><div class="sub">${esc(t.status)} · ${ago(t.created_at)} 시작</div>${ideas || '<div class="empty">아이디어 없음</div>'}`;
  },

  async "/proposals"(filter) {
    const all = await api("/api/factory/proposals");
    const tab = filter || "ALL";
    const shown = all.filter(p => tab === "ALL" || p.status === tab);
    const count = s => all.filter(p => p.status === s).length;
    const byTopic = {};
    shown.forEach(p => (byTopic[p.topic] = byTopic[p.topic] || []).push(p));
    const li = arr => Array.isArray(arr) && arr.length ? `<ul>${arr.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
    const body = Object.entries(byTopic).map(([topic, ps]) => `<h2>${esc(topic)} <span class="mute small">기획안 ${ps.length}건</span></h2>` + ps.map(p => {
      const b = p.body;
      return `<div class="proposal"><div class="head"><span class="t">${esc(b.title)}</span><span class="pill">${PSTAT[p.status]}</span></div>
        <div class="mute small">공수 ${esc(b.effort || "?")} · ${ago(p.created_at)}</div>
        <dl><dt>문제</dt><dd>${esc(b.problem)}</dd><dt>접근</dt><dd>${esc(b.approach)}</dd>
        <dt>DoD</dt><dd>${li(b.dod)}</dd><dt>리스크</dt><dd>${li(b.risks)}</dd>
        <dt>시장</dt><dd>${esc(b.market)}</dd><dt>특허</dt><dd>${esc(b.patent_check)}</dd>
        <dt>첫 단계</dt><dd>${esc(b.first_step)}</dd></dl>
        <details><summary>회의 기록 ${(b.votes || []).length}건</summary>${(b.votes || []).map(v => `<div class="small" style="margin-top:6px"><b>${v.round}R ${esc(v.name)}</b> ${STANCE[v.stance] || v.stance} — ${esc(v.reason)}</div>`).join("")}</details>
        ${p.status === "PENDING" ? `<div class="row" style="margin-top:12px"><input placeholder="사유 (선택)" data-reason="${p.id}" style="flex:1;min-width:160px"><button class="primary" data-decide="${p.id}" data-d="APPROVED">승인</button><button data-decide="${p.id}" data-d="REJECTED">거부</button></div>`
          : `<div class="mute small" style="margin-top:8px">${PSTAT[p.status]} ${p.reason ? "· " + esc(p.reason) : ""}</div>`}
      </div>`;
    }).join("")).join("");
    const tabs = [["ALL", "전체", all.length], ["PENDING", "대기", count("PENDING")], ["APPROVED", "승인", count("APPROVED")], ["REJECTED", "거부", count("REJECTED")]]
      .map(([k, n, c]) => `<button class="${tab === k ? "on" : ""}" data-tab="${k}">${n} ${c}</button>`).join("");
    return `<h1>기획안</h1><div class="sub">회의를 통과해 보고된 아이디어</div><div class="tabs">${tabs}</div>${body || '<div class="empty">없음</div>'}`;
  },

  async "/killed"() {
    const ideas = await api("/api/factory/killed");
    const rows = ideas.map(i => `<div class="card" style="margin-bottom:10px">
      <div class="row" style="justify-content:space-between"><span class="t">${esc(i.title)}</span>${i.review ? `<span class="pill">${i.review === "correct" ? "맞음" : "과잉 폐기"}</span>` : ""}</div>
      <div class="small mute">${esc(i.problem)}</div>
      <div class="small" style="margin-top:6px">${esc(i.verdict_reason)}</div>
      ${i.evidence.map(e => `<div class="small"><a class="mono" href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.number)}</a> ${esc(e.title)} — <span class="mute">${esc(e.element)}</span></div>`).join("")}
      ${i.review ? "" : `<div class="row" style="margin-top:10px"><button data-review="${i.id}" data-v="correct">폐기 맞음</button><button data-review="${i.id}" data-v="overkill">과잉 폐기</button></div>`}
    </div>`).join("");
    return `<h1>폐기 검토</h1><div class="sub">신서사이저 판정을 검토하면 신서사이저 평가에 반영됨</div>${rows || '<div class="empty">폐기된 아이디어 없음</div>'}`;
  },

  async "/staff"() {
    const d = await api("/api/factory/staff");
    const rows = d.staff.map(m => `<tr><td>${esc(m.name)} <span class="mute small">${m.generation}세대</span></td><td class="mono">${esc(m.model_group)}</td>
      <td>${m.samples ?? "-"}</td><td>${m.score == null ? "-" : m.score.toFixed(2)}</td><td><span class="pill">${VERDICT[m.verdict] || m.verdict}</span></td><td class="small mute">${ago(m.hired_at)}</td></tr>`).join("");
    return `<h1>직원</h1><div class="sub">표본 ${d.policy.min_samples}개 이상부터 판정 · ${d.policy.promote_above} 초과 승진 · ${d.policy.retire_below} 미만 퇴출</div>
      <table><tr><th>이름</th><th>모델 그룹</th><th>표본</th><th>점수</th><th>판정</th><th>채용</th></tr>${rows}</table>`;
  },

  async "/projects"() {
    const [projects, runs, questions] = await Promise.all([api("/api/projects"), api("/api/runs"), api("/api/questions")]);
    return `<h1>프로젝트</h1><div class="sub">이 서버에 등록된 프로젝트와 실행</div>
      <h2>프로젝트</h2>${list(projects.map(p => `<div><span class="k mono">${esc(p.project_id)}</span><span>${esc(p.name)}</span></div>`))}
      <h2>실행</h2>${list(runs.map(r => `<div><span class="k mono">${esc(r.run_id)}</span><span>${esc(r.status)}</span></div>`))}
      <h2>대기 질문</h2>${list(questions.map(q => `<div><span class="k mono">${esc(q.question_id)}</span><span>${esc(q.question)}</span></div>`))}`;
  },

  async "/audit"() {
    const rows = await api("/api/factory/audit");
    return `<h1>감사 로그</h1><div class="sub">사람과 정책이 바꾼 모든 것</div>${list(rows.map(a => `<div><span class="k mono">${a.ts.slice(5, 16).replace("T", " ")}</span><span class="pill">${esc(a.actor)}</span><span>${esc(a.action)}</span><span class="mono mute small">${esc(JSON.stringify(a.detail))}</span></div>`))}`;
  },

  async "/emergency"() {
    const s = await api("/api/factory/state");
    return `<h1>비상 통제</h1><div class="sub">KILL은 진행 중인 모든 주제를 취소하고, 해제 전까지 새 주제를 막음</div>
      <div class="row"><span class="dot ${s.loop}">${s.loop}</span><button class="danger" data-act="kill" ${s.loop === "KILLED" ? "disabled" : ""}>전체 KILL</button><button data-act="reset" ${s.loop !== "KILLED" ? "disabled" : ""}>해제</button></div>`;
  },
};
const REFRESH = { "/autonomy": 5000, "/": 15000 };

// ---------------------------------------------------------------- router
async function render() {
  const [path, arg] = parseHash();
  clearTimeout(timer);
  document.querySelectorAll("#navlinks a").forEach(a => a.classList.toggle("on", a.getAttribute("href") === "#" + (path === "/topic" ? "/autonomy" : path)));
  $("#nav").classList.remove("open");
  const page = pages[path] || pages["/"];
  try { view.innerHTML = await page(arg); } catch (e) { if (e.message !== "auth") view.innerHTML = `<h1>오류</h1><div class="empty">${esc(e.message)}</div>`; }
  if (REFRESH[path]) timer = setTimeout(() => { if (!document.activeElement || !view.contains(document.activeElement) || document.activeElement.tagName === "BUTTON") render(); else timer = setTimeout(render, REFRESH[path]); }, REFRESH[path]);
}
function parseHash() {
  const h = location.hash.slice(1) || "/";
  const m = h.match(/^\/(topic|proposals)\/(.+)$/);
  return m ? ["/" + m[1], decodeURIComponent(m[2])] : [h, undefined];
}

view.addEventListener("click", async e => {
  const b = e.target.closest("button"); if (!b) return;
  try {
    if (b.dataset.act) {
      if (b.dataset.act === "kill" && !confirm("진행 중인 모든 주제를 취소합니다. KILL?")) return;
      const r = await api("/api/factory/control", { action: b.dataset.act }); toast("루프: " + r.loop); render();
    } else if (b.dataset.tab) {
      location.hash = b.dataset.tab === "ALL" ? "#/proposals" : "#/proposals/" + b.dataset.tab;
    } else if (b.dataset.decide) {
      const reason = $(`[data-reason="${b.dataset.decide}"]`)?.value || "";
      const r = await api(`/api/factory/proposals/${b.dataset.decide}/decision`, { decision: b.dataset.d, reason });
      toast(b.dataset.d === "APPROVED" ? "승인함" : "거부함"); r.actions.forEach(a => toast(`${a.staff_id} ${a.action}`)); render();
    } else if (b.dataset.review) {
      await api(`/api/factory/ideas/${b.dataset.review}/review`, { verdict: b.dataset.v }); toast("검토 반영"); render();
    }
  } catch (err) { toast("실패: " + err.message); }
});
view.addEventListener("submit", async e => {
  if (e.target.id !== "topicform") return;
  e.preventDefault();
  const text = $("#topictext").value.trim(); if (!text) return;
  try { const r = await api("/api/factory/topics", { text }); toast("시작: " + r.topic_id); render(); } catch (err) { toast("실패: " + err.message); }
});
$("#navsearch").addEventListener("input", e => {
  const q = e.target.value.trim();
  document.querySelectorAll("#navlinks a").forEach(a => a.style.display = !q || a.textContent.includes(q) ? "" : "none");
  document.querySelectorAll("#navlinks .sec").forEach(s => s.style.display = q ? "none" : "");
});
$("#menu").addEventListener("click", () => $("#nav").classList.toggle("open"));
$("#logout").addEventListener("click", async () => { await fetch("/api/logout", { method: "POST" }); location = "/login"; });
window.addEventListener("hashchange", render);
render();
