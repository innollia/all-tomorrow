"use strict";
// Idea desk: 아이디어 원문 → 자료봉용 전체 프롬프트(복사) → 하위 결과 붙여넣기 → 결과 목록·관제용 정리본.
// API: /api/ideas/* (console/ideas.py). 모델을 부르지 않는다.
(() => {
  const { $, view, esc, api, toast, ago, list } = AT;
  AT.nav.push({ section: "기획", label: "아이디어 조사", href: "#/ideas", order: 39 });
  AT.navAlias = Object.assign(AT.navAlias || {}, { "/idea": "/ideas" });
  let current = null;  // last opened idea, for the copy buttons

  AT.pages["/ideas"] = async () => {
    const ideas = await api("/api/ideas");
    const rows = ideas.map(i => `<div><span class="k">${ago(i.updated_at)}</span>
      <a href="#/idea/${encodeURIComponent(i.id)}" style="flex:1">${esc(i.title)}</a>
      <span class="small mute mono">${esc(i.id)}</span><span class="pill">하위 ${i.subtasks} · 결과 ${i.results}</span></div>`);
    return `<h1>아이디어 조사</h1><div class="sub">아이디어를 넣으면 자료봉에게 줄 전체 프롬프트를 만든다 · 결과는 여기 모아 관제가 읽는다</div>
      <form id="idea-new" class="card">
        <input id="idea-title" placeholder="제목 (비우면 첫 줄)" maxlength="200" style="margin-bottom:8px">
        <textarea id="idea-text" rows="8" placeholder="아이디어 텍스트 뭉탱이를 그대로 붙여넣기"></textarea>
        <div class="row" style="margin-top:8px"><button class="primary">프롬프트 만들기</button></div>
      </form>
      <h2>아이디어</h2>${list(rows)}`;
  };

  AT.pages["/idea/"] = async id => {
    const i = current = await api(`/api/ideas/${encodeURIComponent(id)}`);
    const results = i.results.map(r => `<div style="display:block">
      <div class="row"><b>${esc(r.subtask_id)}</b><span style="flex:1">${esc(r.subtask_title || (r.subtask_id === "?" ? "형식 밖 결과" : ""))}</span><span class="small mute">${ago(r.created_at)}</span></div>
      <details><summary>본문 ${r.body.length}자</summary><pre class="small" style="white-space:pre-wrap">${esc(r.body)}</pre></details></div>`);
    return `<h1>${esc(i.title)}</h1><div class="sub mono">${esc(i.id)} · ${ago(i.created_at)} 생성</div>
      <h2>1 · 원문</h2><details><summary>${i.text.length}자</summary><pre class="small" style="white-space:pre-wrap">${esc(i.text)}</pre></details>
      <h2>2 · 자료봉에게 줄 전체 프롬프트</h2>
      <div class="row" style="margin-bottom:8px"><button class="primary" data-icopy="prompt">전체 프롬프트 복사</button><span class="small mute">자료봉이 하위 프롬프트 S1…Sn을 돌려준다 → 각각 새 세션에 붙여 병렬로 돌린다</span></div>
      <details><summary>프롬프트 보기 (${i.prompt.length}자)</summary><pre class="small" style="white-space:pre-wrap">${esc(i.prompt)}</pre></details>
      <h2>3 · 결과 붙여넣기</h2>
      <form id="idea-paste"><textarea id="idea-paste-text" rows="8" placeholder="=== 자료봉 결과 === … === 끝 === 블록. 여러 개를 한꺼번에 붙여도 된다"></textarea>
        <div class="row" style="margin-top:8px"><button class="primary">결과 저장</button></div></form>
      <h2>4 · 결과 (${i.results.length})</h2>${list(results)}
      <h2>5 · 관제용 정리본</h2>
      <div class="row"><button data-icopy="brief">정리본 복사</button><span class="small mute mono">${esc(i.brief_path)}</span></div>`;
  };

  async function copy(text) {
    try { await navigator.clipboard.writeText(text); }
    catch {  // http without a secure context: fall back to a hidden textarea
      const t = document.createElement("textarea"); t.value = text; document.body.appendChild(t); t.select();
      document.execCommand("copy"); t.remove();
    }
    toast("복사함 (" + text.length + "자)");
  }

  view.addEventListener("click", e => {
    const b = e.target.closest("button[data-icopy]"); if (!b || !current) return;
    copy(b.dataset.icopy === "prompt" ? current.prompt : current.brief);
  });
  view.addEventListener("submit", async e => {
    if (e.target.id === "idea-new") {
      e.preventDefault();
      const text = $("#idea-text").value.trim(); if (!text) return;
      try { const r = await api("/api/ideas", { title: $("#idea-title").value, text }); location.hash = "#/idea/" + encodeURIComponent(r.id); }
      catch (err) { toast("실패: " + err.message); }
    } else if (e.target.id === "idea-paste" && current) {
      e.preventDefault();
      const text = $("#idea-paste-text").value.trim(); if (!text) return;
      try {
        const r = await api(`/api/ideas/${encodeURIComponent(current.id)}/results`, { text });
        toast("저장: " + r.added.map(a => a.subtask_id || "?").join(", ")); AT.render();
      } catch (err) { toast("실패: " + err.message); }
    }
  });
})();
