"use strict";
// Idea desk: 아이디어 원문 → 자료봉용 전체 프롬프트(복사) → 하위 결과 붙여넣기 → 결과 목록·관제용 정리본.
// API: /api/ideas/* (console/ideas.py). 모델을 부르지 않는다.
(() => {
  const { $, view, esc, api, toast, ago, list } = AT;
  AT.nav.push({ section: "기획", label: "아이디어 조사", href: "#/ideas", order: 39 });
  AT.navAlias = Object.assign(AT.navAlias || {}, { "/idea": "/ideas" });
  let current = null;  // last opened idea, for the copy buttons
  // Unsaved text survives a failed save, a reload or leaving the page (per browser, best effort).
  const draftKey = id => "at-ideas-draft:" + id;
  const draft = {
    get(id) { try { return localStorage.getItem(draftKey(id)) || ""; } catch { return ""; } },
    set(id, v) { try { v ? localStorage.setItem(draftKey(id), v) : localStorage.removeItem(draftKey(id)); } catch {} },
  };
  const DRAFTED = { "idea-title": () => "new-title", "idea-text": () => "new-text",
    "idea-plan-text": () => current && current.id + ":plan", "idea-paste-text": () => current && current.id + ":paste" };

  AT.pages["/ideas"] = async () => {
    const ideas = await api("/api/ideas");
    const day = t => esc(String(t || "").slice(0, 10));
    const rows = ideas.map(i => {
      const c = i.status_counts;
      return `<div style="flex-wrap:wrap"><a href="#/idea/${encodeURIComponent(i.id)}" style="flex:1;min-width:180px">${esc(i.title)}</a>
      <span class="small mute mono">${esc(i.id)} · 만든 날 ${day(i.created_at)}</span>
      <span class="pill">과제 ${i.subtasks}${i.plan_at ? "" : " · 쪼개기 없음"}</span>
      <span class="pill">완료 ${c["완료"]} · 불완전 ${c["불완전"]} · 실패 ${c["실패"]}${c[""] ? " · 상태없음 " + c[""] : ""}</span>
      <span class="small mute">결과 ${i.results}개 · 갱신 ${ago(i.updated_at)}</span></div>`;
    });
    return `<h1>아이디어 조사</h1><div class="sub">아이디어를 넣으면 자료봉에게 줄 전체 프롬프트를 만든다 · 결과는 여기 모아 관제가 읽는다</div>
      <form id="idea-new" class="card">
        <input id="idea-title" placeholder="제목 (비우면 첫 줄)" maxlength="200" style="margin-bottom:8px" value="${esc(draft.get("new-title"))}">
        <textarea id="idea-text" rows="8" placeholder="아이디어 텍스트 뭉탱이를 그대로 붙여넣기">${esc(draft.get("new-text"))}</textarea>
        <div class="row" style="margin-top:8px"><button class="primary">프롬프트 만들기</button></div>
      </form>
      <h2>아이디어</h2>${list(rows)}`;
  };

  AT.pages["/idea/"] = async id => {
    const i = current = await api(`/api/ideas/${encodeURIComponent(id)}`);
    const claim = c => `<div class="small" style="margin-top:6px"><b>${esc(c.id)}</b> ${esc(c.claim)}
      ${c.kind ? `<span class="pill">${esc(c.kind)}</span>` : ""}
      <div class="mute">${/^https?:\/\//.test(c.source) ? `<a href="${esc(c.source)}" target="_blank" rel="noopener">${esc(c.source)}</a>` : esc(c.source) || '<span style="color:var(--bad)">출처 없음</span>'}${c.quote ? ` — ${esc(c.quote)}` : ""}</div></div>`;
    const results = i.results.map(r => `<div style="display:block">
      <div class="row"><b>${esc(r.subtask_id)}</b><span class="pill"${r.latest ? "" : ' style="opacity:.6"'}>${r.latest ? "최신" : "이전(덮어씀)"}</span><span style="flex:1">${esc(r.subtask_title || (r.subtask_id === "?" ? "형식 밖 결과" : ""))}</span>
        <span class="pill"${r.status && r.status !== "완료" ? ' style="color:var(--warn)"' : ""}>${esc(r.status || "상태 없음")}</span>
        <span class="small mute">주장 ${r.claims.length} · 출처 없음 ${r.claims.filter(c => !c.source).length}</span><span class="small mute">${ago(r.created_at)}</span><button class="danger" data-idel-result="${r.id}">삭제</button></div>
      ${r.claims.map(claim).join("")}
      <details><summary>본문 ${r.body.length}자</summary><pre class="small" style="white-space:pre-wrap">${esc(r.body)}</pre></details></div>`);
    return `<div class="row" style="justify-content:space-between"><h1>${esc(i.title)}</h1><button class="danger" data-idel-idea="1">아이디어 삭제</button></div>
      <div class="sub mono">${esc(i.id)} · ${ago(i.created_at)} 생성</div>
      <h2>1 · 원문</h2><textarea rows="6" readonly>${esc(i.text)}</textarea>
      <h2>2 · 자료봉에게 줄 전체 프롬프트</h2>
      <div class="row" style="margin-bottom:8px"><button class="primary" data-icopy="prompt">전체 프롬프트 복사</button><span class="small mute">자료봉이 하위 프롬프트 S1…Sn을 돌려준다 → 각각 새 세션에 붙여 병렬로 돌린다</span></div>
      <details><summary>프롬프트 보기 (${i.prompt.length}자)</summary><pre class="small" style="white-space:pre-wrap">${esc(i.prompt)}</pre></details>
      <h2>2-1 · 자료봉의 과제 쪼개기 답</h2>
      ${i.plan ? `<details${i.results.length ? "" : " open"}><summary>저장됨 · ${ago(i.plan_at)} · ${i.plan.length}자</summary><pre class="small" style="white-space:pre-wrap">${esc(i.plan)}</pre></details>${i.plans.slice(1).map(o => `<details><summary>이전 쪼개기 · ${ago(o.created_at)} · ${o.text.length}자</summary><pre class="small" style="white-space:pre-wrap">${esc(o.text)}</pre></details>`).join("")}` : '<div class="small mute">자료봉이 돌려준 분석·불확실성·과제 표(하위 프롬프트 포함 전체)를 붙여넣어 두면 정리본에 같이 들어간다</div>'}
      <form id="idea-plan" style="margin-top:8px"><textarea id="idea-plan-text" rows="8" placeholder="자료봉 답 전체 붙여넣기 (저장하면 이전 것을 바꾼다)">${esc(draft.get(i.id + ":plan") || i.plan)}</textarea>
        <div class="row" style="margin-top:8px"><button>${i.plan ? "바꿔 저장" : "저장"}</button></div></form>
      <h2>3 · 결과 붙여넣기</h2>
      <form id="idea-paste"><textarea id="idea-paste-text" rows="8" placeholder="=== 자료봉 결과 === … === 끝 === 블록. 여러 개를 한꺼번에 붙여도 된다">${esc(draft.get(i.id + ":paste"))}</textarea>
        <div class="row" style="margin-top:8px"><button class="primary">결과 저장</button></div></form>
      <h2>4 · 결과 (${i.results.length}, 덮어쓴 것 포함 · 최신 순)</h2>${list(results)}
      <h2>5 · 관제용 정리본</h2>
      <div class="row"><button class="primary" data-icopy="overseer">관제에게 가져가기</button><button data-icopy="brief">정리본 복사</button><span class="small mute mono">${esc(i.brief_path)}</span></div>`;
  };

  async function copy(text) {
    try { await navigator.clipboard.writeText(text); }
    catch {  // http without a secure context: fall back to a hidden textarea
      const t = document.createElement("textarea"); t.value = text; document.body.appendChild(t); t.select();
      document.execCommand("copy"); t.remove();
    }
    toast("복사함 (" + text.length + "자)");
  }

  view.addEventListener("click", async e => {
    const b = e.target.closest("button"); if (!b || !current || !view.contains(b)) return;
    const d = b.dataset, base = `/api/ideas/${encodeURIComponent(current.id)}`;
    try {
      if (d.icopy) copy(d.icopy === "prompt" ? current.prompt : d.icopy === "overseer"
        ? `아이디어 ${current.id} 조사 결과 보고 얘기하자 — 정리본 ${current.brief_path}` : current.brief);
      else if (d.idelIdea) {
        if (!confirm(`아이디어 "${current.title}"와 결과 ${current.results.length}개를 지운다. 되돌릴 수 없다.`)) return;
        await api(base, undefined, "DELETE"); toast("삭제함"); location.hash = "#/ideas";
      } else if (d.idelResult) {
        const r = current.results.find(x => String(x.id) === d.idelResult);
        if (!confirm(`결과 ${r ? r.subtask_id + " " + r.subtask_title : ""}를 지운다. 되돌릴 수 없다.`)) return;
        await api(`${base}/results/${d.idelResult}`, undefined, "DELETE"); toast("결과 삭제함"); AT.render();
      }
    } catch (err) { toast("실패: " + err.message); }
  });
  view.addEventListener("input", e => {
    const key = DRAFTED[e.target.id]?.(); if (key) draft.set(key, e.target.value);
  });
  view.addEventListener("submit", async e => {
    if (e.target.id === "idea-new") {
      e.preventDefault();
      const text = $("#idea-text").value.trim(); if (!text) return;
      try { const r = await api("/api/ideas", { title: $("#idea-title").value, text }); draft.set("new-title", ""); draft.set("new-text", ""); location.hash = "#/idea/" + encodeURIComponent(r.id); }
      catch (err) { toast("실패: " + err.message); }
    } else if (e.target.id === "idea-plan" && current) {
      e.preventDefault();
      const text = $("#idea-plan-text").value.trim(); if (!text) return;
      if (text === current.plan) { draft.set(current.id + ":plan", ""); toast("바뀐 것 없음"); return; }
      try { await api(`/api/ideas/${encodeURIComponent(current.id)}/plan`, { text }, "PUT"); draft.set(current.id + ":plan", ""); toast("과제 쪼개기 저장"); AT.render(); }
      catch (err) { toast("실패: " + err.message); }
    } else if (e.target.id === "idea-paste" && current) {
      e.preventDefault();
      const text = $("#idea-paste-text").value.trim(); if (!text) return;
      try {
        const r = await api(`/api/ideas/${encodeURIComponent(current.id)}/results`, { text });
        draft.set(current.id + ":paste", ""); toast("저장: " + r.added.map(a => a.subtask_id || "?").join(", ")); AT.render();
      } catch (err) { toast("실패: " + err.message); }
    }
  });
})();
