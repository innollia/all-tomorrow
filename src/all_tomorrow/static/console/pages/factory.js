"use strict";
// Idea factory: 통제면 · 주제 · 기획안 · 폐기 검토 · 직원 · 감사 로그 · 비상 통제. API: /api/factory/* (console/factory.py).
(() => {
  const { $, view, esc, api, toast, ago, list } = AT;
  const STANCE = { support: "지지", oppose: "반대", conditional: "조건부" };
  const IDEA = { GENERATED: "생성", KILLED: "폐기", HELD: "보류", IN_COUNCIL: "회의중", REJECTED: "회의 탈락", PROPOSED: "기획안" };
  const PSTAT = { PENDING: "대기", APPROVED: "승인", REJECTED: "거부" };
  const VERDICT = { EVALUATING: "평가중", KEEP: "유지", PROMOTE: "승진 대상", RETIRE: "퇴출 대상", RETIRED: "퇴출" };

  AT.nav.push(
    { section: "자율 레이어", label: "통제면", href: "#/autonomy", order: 30 },
    { section: "자율 레이어", label: "폐기 검토", href: "#/killed", order: 31 },
    { section: "기획", label: "기획안", href: "#/proposals", order: 40 },
    { section: "기획", label: "직원", href: "#/staff", order: 41 },
    { section: "보안·접근", label: "감사 로그", href: "#/audit", order: 70 },
    { section: "보안·접근", label: "비상 통제", href: "#/emergency", order: 71 },
  );
  AT.navAlias = Object.assign(AT.navAlias || {}, { "/topic": "/autonomy" });

  AT.home.push({ order: 40, render: async () => {
    const s = await api("/api/factory/state").catch(() => null);
    if (!s) return "";
    return `<a class="card" href="#/autonomy"><div class="mute small">루프</div><div class="stat dot ${esc(s.loop)}">${esc(s.loop)}</div></a>
      <a class="card" href="#/proposals"><div class="mute small">대기 기획안</div><div class="stat">${s.counts.PENDING}</div></a>
      <a class="card" href="#/autonomy"><div class="mute small">진행 중 주제</div><div class="stat">${s.topics.filter(t => t.status === "RUNNING").length}</div></a>
      <a class="card" href="#/staff"><div class="mute small">재직 직원</div><div class="stat">${s.staff.length}</div></a>`;
  } });

  const votes = (vs, who) => vs.map(v => `<div class="small" style="margin-top:6px"><b>${v.round}R ${esc(who(v))}</b> ${STANCE[v.stance] || esc(v.stance)} — ${esc(v.reason)}</div>`).join("");
  const evidence = es => (es || []).map(e => `<div class="small"><a class="mono" href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.number)}</a> ${esc(e.title)} — <span class="mute">${esc(e.element)}</span></div>`).join("");

  AT.pages["/autonomy"] = async () => {
    const [s, events] = await Promise.all([api("/api/factory/state"), api("/api/factory/events?limit=60")]);
    const staff = s.staff.map(m => `<div class="card"><div class="t">${esc(m.name)}</div><div class="mono mute">${esc(m.model_group)} · ${m.generation}세대</div><div class="small" style="margin-top:8px">${esc(m.last) || '<span class="mute">발언 없음</span>'}</div></div>`).join("");
    const topics = s.topics.map(t => `<div><span class="k">${ago(t.created_at)}</span><a href="#/topic/${encodeURIComponent(t.id)}" style="flex:1">${esc(t.text)}</a><span class="small mute">${Object.entries(t.idea_counts).map(([k, v]) => `${IDEA[k] || esc(k)} ${v}`).join(" · ")}</span><span class="pill">${esc(t.status)}</span></div>`);
    const log = events.map(e => `<div><span class="k mono">${esc(e.ts.slice(11, 19))}</span><span class="pill">${esc(e.kind)}</span><span>${esc(e.text)}</span></div>`);
    const can = s.loop !== "KILLED";
    return `<h1>통제면</h1><div class="sub">루프 상태와 직원 발언 · 5초마다 갱신</div>
      <div class="row"><span class="dot ${esc(s.loop)}">${esc(s.loop)}</span>
        <button data-fact="pause" ${s.loop !== "RUN" ? "disabled" : ""}>일시정지</button>
        <button data-fact="resume" ${s.loop !== "PAUSED" ? "disabled" : ""}>재개</button>
        <button class="danger" data-fact="kill" ${!can ? "disabled" : ""}>KILL</button>
        <button data-fact="reset" ${can ? "disabled" : ""}>해제</button>
        <span class="mute small">기획안 누적 ${s.proposed_total}</span></div>
      <h2>주제 던지기</h2>
      ${s.runtime ? `<form id="factory-topic" class="row"><input id="factory-topic-text" placeholder="예: TRPG 유틸리티" style="flex:1;min-width:200px" ${can ? "" : "disabled"}><button class="primary" ${can ? "" : "disabled"}>시작</button></form>`
        : `<div class="mute small">이 서버 프로세스에는 실행기가 없어 주제를 시작할 수 없음 (IDEA_FACTORY_ENABLED=1 필요)</div>`}
      <h2>직원</h2>${staff ? `<div class="grid">${staff}</div>` : '<div class="empty">없음</div>'}
      <h2>주제</h2>${list(topics)}
      <h2>이벤트</h2>${list(log)}`;
  };
  AT.refresh["/autonomy"] = 5000;

  AT.pages["/topic/"] = async id => {
    const t = await api("/api/factory/topics/" + encodeURIComponent(id));
    const ideas = t.ideas.slice().sort((a, b) => a.idx - b.idx).map(i => `<div class="card" style="margin-bottom:10px">
      <div class="row" style="justify-content:space-between"><span class="t">${esc(i.title)}</span><span class="pill">${IDEA[i.status] || esc(i.status)}</span></div>
      <div class="small" style="margin-top:6px">${esc(i.problem)}</div><div class="small mute">${esc(i.approach)}</div>
      ${i.verdict_reason ? `<div class="small" style="margin-top:6px"><span class="mute">신서사이저:</span> ${esc(i.verdict_reason)}</div>` : ""}
      ${evidence(i.evidence)}
      ${i.votes.length ? `<details><summary>회의 ${i.votes.length}건</summary>${votes(i.votes, v => v.staff_id)}</details>` : ""}
    </div>`).join("");
    return `<h1>${esc(t.text)}</h1><div class="sub">${esc(t.status)} · ${ago(t.created_at)} 시작</div>${ideas || '<div class="empty">아이디어 없음</div>'}`;
  };

  const proposals = async filter => {
    const all = await api("/api/factory/proposals");
    const tab = filter || "ALL";
    const shown = all.filter(p => tab === "ALL" || p.status === tab);
    const count = s => all.filter(p => p.status === s).length;
    const byTopic = {};
    shown.forEach(p => (byTopic[p.topic] = byTopic[p.topic] || []).push(p));
    const li = arr => Array.isArray(arr) && arr.length ? `<ul>${arr.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
    const body = Object.entries(byTopic).map(([topic, ps]) => `<h2>${esc(topic)} <span class="mute small">기획안 ${ps.length}건</span></h2>` + ps.map(p => {
      const b = p.body;
      return `<div class="proposal"><div class="head"><span class="t">${esc(b.title)}</span><span class="pill">${PSTAT[p.status] || esc(p.status)}</span></div>
        <div class="mute small">공수 ${esc(b.effort || "?")} · ${ago(p.created_at)}</div>
        <dl><dt>문제</dt><dd>${esc(b.problem)}</dd><dt>접근</dt><dd>${esc(b.approach)}</dd>
        <dt>DoD</dt><dd>${li(b.dod)}</dd><dt>리스크</dt><dd>${li(b.risks)}</dd>
        <dt>시장</dt><dd>${esc(b.market)}</dd><dt>특허</dt><dd>${esc(b.patent_check)}</dd>
        <dt>첫 단계</dt><dd>${esc(b.first_step)}</dd></dl>
        <details><summary>회의 기록 ${(b.votes || []).length}건</summary>${votes(b.votes || [], v => v.name)}</details>
        ${p.status === "PENDING" ? `<div class="row" style="margin-top:12px"><input placeholder="사유 (선택)" data-freason="${esc(p.id)}" style="flex:1;min-width:160px"><button class="primary" data-fdecide="${esc(p.id)}" data-d="APPROVED">승인</button><button data-fdecide="${esc(p.id)}" data-d="REJECTED">거부</button></div>`
          : `<div class="mute small" style="margin-top:8px">${PSTAT[p.status] || esc(p.status)} ${p.reason ? "· " + esc(p.reason) : ""}</div>`}
      </div>`;
    }).join("")).join("");
    const tabs = [["ALL", "전체", all.length], ["PENDING", "대기", count("PENDING")], ["APPROVED", "승인", count("APPROVED")], ["REJECTED", "거부", count("REJECTED")]]
      .map(([k, n, c]) => `<button class="${tab === k ? "on" : ""}" data-ftab="${k}">${n} ${c}</button>`).join("");
    return `<h1>기획안</h1><div class="sub">회의를 통과해 보고된 아이디어</div><div class="tabs">${tabs}</div>${body || '<div class="empty">없음</div>'}`;
  };
  AT.pages["/proposals"] = () => proposals();
  AT.pages["/proposals/"] = filter => proposals(filter);

  AT.pages["/killed"] = async () => {
    const ideas = await api("/api/factory/killed");
    const rows = ideas.map(i => `<div class="card" style="margin-bottom:10px">
      <div class="row" style="justify-content:space-between"><span class="t">${esc(i.title)}</span>${i.review ? `<span class="pill">${i.review === "correct" ? "맞음" : "과잉 폐기"}</span>` : ""}</div>
      <div class="small mute">${esc(i.problem)}</div>
      <div class="small" style="margin-top:6px">${esc(i.verdict_reason)}</div>
      ${evidence(i.evidence)}
      ${i.review ? "" : `<div class="row" style="margin-top:10px"><button data-freview="${esc(i.id)}" data-v="correct">폐기 맞음</button><button data-freview="${esc(i.id)}" data-v="overkill">과잉 폐기</button></div>`}
    </div>`).join("");
    return `<h1>폐기 검토</h1><div class="sub">신서사이저 판정을 검토하면 신서사이저 평가에 반영됨</div>${rows || '<div class="empty">폐기된 아이디어 없음</div>'}`;
  };

  AT.pages["/staff"] = async () => {
    const d = await api("/api/factory/staff");
    const rows = d.staff.map(m => `<tr><td>${esc(m.name)} <span class="mute small">${m.generation}세대</span></td><td class="mono">${esc(m.model_group)}</td>
      <td class="small">L${m.access_level ?? 0}${(m.access_scopes || []).length ? " · " + esc(m.access_scopes.join(", ")) : ""}</td><td>${m.samples ?? "-"}</td><td>${m.score == null ? "-" : m.score.toFixed(2)}</td><td><span class="pill">${VERDICT[m.verdict] || esc(m.verdict || "-")}</span></td><td class="small mute">${ago(m.hired_at)}</td></tr>`).join("");
    const policy = d.policy ? `표본 ${d.policy.min_samples}개 이상부터 판정 · ${d.policy.promote_above} 초과 승진 · ${d.policy.retire_below} 미만 퇴출`
      : "평가 정책 없음 (config/idea-factory.yaml을 읽지 못함)";
    return `<h1>직원</h1><div class="sub">${policy}</div>
      ${rows ? `<table><tr><th>이름</th><th>모델 그룹</th><th>의뢰인 정보 권한</th><th>표본</th><th>점수</th><th>판정</th><th>채용</th></tr>${rows}</table>` : '<div class="empty">없음</div>'}`;
  };

  AT.pages["/audit"] = async () => {
    const rows = await api("/api/factory/audit");
    return `<h1>감사 로그</h1><div class="sub">사람과 정책이 바꾼 모든 것</div>${list(rows.map(a => `<div><span class="k mono">${esc(a.ts.slice(5, 16).replace("T", " "))}</span><span class="pill">${esc(a.actor)}</span><span>${esc(a.action)}</span><span class="mono mute small">${esc(JSON.stringify(a.detail))}</span></div>`))}`;
  };

  AT.pages["/emergency"] = async () => {
    const s = await api("/api/factory/state");
    return `<h1>비상 통제</h1><div class="sub">KILL은 진행 중인 모든 주제를 취소하고, 해제 전까지 새 주제를 막음</div>
      <div class="row"><span class="dot ${esc(s.loop)}">${esc(s.loop)}</span><button class="danger" data-fact="kill" ${s.loop === "KILLED" ? "disabled" : ""}>전체 KILL</button><button data-fact="reset" ${s.loop !== "KILLED" ? "disabled" : ""}>해제</button></div>`;
  };

  // Handlers listen on the shared view but react only to this feature's data-f* attributes.
  view.addEventListener("click", async e => {
    const b = e.target.closest("button"); if (!b || !view.contains(b)) return;
    const d = b.dataset;
    if (!(d.fact || d.ftab || d.fdecide || d.freview)) return;
    try {
      if (d.fact) {
        if (d.fact === "kill" && !confirm("진행 중인 모든 주제를 취소합니다. KILL?")) return;
        const r = await api("/api/factory/control", { action: d.fact }); toast("루프: " + r.loop); AT.render();
      } else if (d.ftab) {
        location.hash = d.ftab === "ALL" ? "#/proposals" : "#/proposals/" + d.ftab;
      } else if (d.fdecide) {
        const reason = [...view.querySelectorAll("[data-freason]")].find(el => el.dataset.freason === d.fdecide)?.value || "";
        const r = await api(`/api/factory/proposals/${encodeURIComponent(d.fdecide)}/decision`, { decision: d.d, reason });
        toast(d.d === "APPROVED" ? "승인함" : "거부함"); r.actions.forEach(a => toast(`${a.staff_id} ${a.action}`)); AT.render();
      } else if (d.freview) {
        await api(`/api/factory/ideas/${encodeURIComponent(d.freview)}/review`, { verdict: d.v }); toast("검토 반영"); AT.render();
      }
    } catch (err) { toast("실패: " + err.message); }
  });
  view.addEventListener("submit", async e => {
    if (e.target.id !== "factory-topic") return;
    e.preventDefault();
    const text = $("#factory-topic-text").value.trim(); if (!text) return;
    try { const r = await api("/api/factory/topics", { text }); toast("시작: " + r.topic_id); AT.render(); } catch (err) { toast("실패: " + err.message); }
  });
})();
