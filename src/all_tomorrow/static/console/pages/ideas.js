"use strict";
// Idea desk: 아이디어 원문 → 자료봉용 전체 프롬프트(복사) → 하위 결과 붙여넣기 → 결과 목록·관제용 정리본(짧은 종합본).
// API: /api/ideas/* (console/ideas.py). 자유 자료(intake)만 서버가 Jev로 아이디어·과제를 가른다.
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
  const SLOTS = 7;  // result boxes: 3-5 tasks by default, plus retries and cross-checks
  const slotKey = n => current && current.id + ":paste" + n;
  const DRAFTED = { "intake-text": () => "intake:" + (current && location.hash.startsWith("#/idea/") ? current.id : ""), "idea-title": () => "new-title", "idea-text": () => "new-text",
    "idea-plan-text": () => current && current.id + ":plan", "fu-text": () => current && current.id + ":fu" };
  for (let n = 0; n < SLOTS; n++) DRAFTED["idea-slot-" + n] = () => slotKey(n);

  // 자유 자료 넣기: 붙여넣기 칸 하나 + 파일 + 넣기 버튼. 아이디어를 고르지 않으면 서버(Jev)가 맞는 걸 고른다.
  const intakeForm = (ideas, fixed) => `<form id="idea-intake" class="card" style="margin-bottom:${fixed ? 0 : 16}px">
    <div class="t">자료 넣기</div>
    <textarea id="intake-text" rows="6" placeholder="조사한 것을 그대로 붙여넣기. 형식 상관없음 (대화, 메모, 표, 링크, 아주 긴 글도 됨)" style="font-size:16px;margin-top:8px;width:100%">${esc(draft.get("intake:" + (fixed || "")))}</textarea>
    <div class="row" style="margin-top:8px;flex-wrap:wrap;gap:8px">
      <input id="intake-files" type="file" multiple style="flex:1;min-width:200px;font-size:16px" aria-label="파일 첨부">
      ${fixed ? "" : `<select id="intake-idea" aria-label="아이디어" style="flex:1;min-width:160px;font-size:16px;min-height:44px"><option value="">아이디어: 알아서 고르기</option>${ideas.map(i => `<option value="${esc(i.id)}">${esc(i.title)}</option>`).join("")}</select>`}
      <button class="primary" style="min-height:44px;min-width:110px;font-size:16px">자료 넣기</button></div>
    <div id="intake-result" class="small" style="margin-top:8px"></div></form>`;

  // 홈 첫 화면에도 같은 입력칸을 둔다. 아이디어는 안 골라도 된다.
  AT.home.push({ order: 1, render: async () => {
    const ideas = await api("/api/ideas").catch(() => []);
    return `<div style="grid-column:1/-1">${intakeForm(ideas, "")}</div>`;
  } });

  const readFile = f => new Promise((ok, no) => {
    const r = new FileReader(); r.onerror = () => no(new Error(f.name + " 읽기 실패"));
    r.onload = () => ok({ name: f.name, data: String(r.result).split(",")[1] || "" }); r.readAsDataURL(f);
  });
  const KIND = { paste: "붙여넣은 글", url: "링크", file: "파일", result: "자료봉 결과 블록" };
  const HOW = { user: "고른 아이디어에", jev: "Jev가 이 아이디어로 판단", new: "맞는 아이디어가 없어 새 아이디어 후보로", id: "블록의 아이디어 ID대로", free: "" };
  // 한 줄: 무엇으로 이해했고 어디에 넣었나. 옮길 수 있는 자료에는 아이디어 고르기를 붙인다.
  const placedLine = (a, ideas) => {
    const what = `${KIND[a.kind] || esc(a.kind)} · ${esc(a.title)}`;
    const where = a.kind === "result" ? "결과로 저장" : `${esc(a.idea_title)}${a.candidate ? " (새 후보)" : ""}${a.task_id ? " · " + esc(a.task_id) : " · 자유 자료"}`;
    const move = a.material_id ? `<select data-imove="${a.material_id}" data-from="${esc(a.idea_id)}" aria-label="다른 아이디어로 옮기기" style="font-size:16px;min-height:44px;max-width:100%"><option value="">다른 아이디어로 옮기기</option>${ideas.filter(i => i.id !== a.idea_id).map(i => `<option value="${esc(i.id)}">${esc(i.title)}</option>`).join("")}</select>` : "";
    return `<div class="row" style="flex-wrap:wrap;gap:6px;margin-top:6px"><span style="flex:1;min-width:200px">${what} → <b>${where}</b> <span class="mute">(${HOW[a.placed_by] || "알아서"})${a.kind === "result" ? "" : " · 곧 짧게 정리됨"}</span></span>${move}</div>`;
  };
  // 종합본은 마크다운이다. 제목(#)과 굵게(**)만 살리고 나머지는 글 그대로 둔다.
  const md = t => esc(t).replace(/^#{1,4} +(.+)$/gm, '<b class="idea-h">$1</b>').replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>");
  const FSTATE = { RUNNING: "도는 중", SUCCESS: "끝", FAILED: "실패", INTERRUPTED: "끊김", LOST: "잃어버림" };

  AT.pages["/ideas"] = async () => {
    const ideas = await api("/api/ideas");
    const rows = ideas.map(i => `<a class="idea-row" href="#/idea/${encodeURIComponent(i.id)}">
      <span class="idea-row-title">${esc(i.title)}${i.candidate ? ' <span class="pill warn">후보</span>' : ""}${i.pending ? ` <span class="pill warn">압축 대기 ${i.pending}</span>` : ""}</span>
      <span class="small mute">자료 ${i.materials || 0} · 결과 ${i.results} · ${i.synth_at ? "종합 " + ago(i.synth_at) : "종합 전"} · 갱신 ${ago(i.updated_at)}</span></a>`);
    return `<h1>아이디어 조사</h1>
      ${intakeForm(ideas, "")}
      <h2>아이디어 (${ideas.length})</h2>${list(rows)}
      <details style="margin-top:20px"><summary style="min-height:44px">새 아이디어 직접 만들기 (자료봉 프롬프트용)</summary>
      <form id="idea-new">
        <input id="idea-title" placeholder="제목 (비우면 첫 줄)" maxlength="200" style="margin:8px 0;font-size:16px" value="${esc(draft.get("new-title"))}">
        <textarea id="idea-text" rows="8" placeholder="아이디어 텍스트 뭉탱이를 그대로 붙여넣기" style="font-size:16px">${esc(draft.get("new-text"))}</textarea>
        <div class="row" style="margin-top:8px"><button class="primary" style="min-height:44px">프롬프트 만들기</button></div>
      </form></details>`;
  };

  AT.pages["/idea/"] = async id => {
    const i = current = await api(`/api/ideas/${encodeURIComponent(id)}`);
    const others = (await api("/api/ideas").catch(() => [])).filter(x => x.id !== i.id);
    const claim = c => `<div class="small" style="margin-top:6px"><b>${esc(c.id)}</b> ${esc(c.claim)}
      ${c.kind ? `<span class="pill">${esc(c.kind)}</span>` : ""}
      <div class="mute">${/^https?:\/\//.test(c.source) ? `<a href="${esc(c.source)}" target="_blank" rel="noopener">${esc(c.source)}</a>` : esc(c.source) || '<span style="color:var(--bad)">출처 없음</span>'}${c.quote ? ` — ${esc(c.quote)}` : ""}</div></div>`;
    // Paragraphs Jev judged to be the researcher's own opinion or chatter are folded, never removed.
    const planView = idea => (idea.plan_paras || []).some(p => !p.keep)
      ? idea.plan_paras.map(p => p.keep ? `<pre class="small" style="white-space:pre-wrap">${esc(p.text)}</pre>`
        : `<details style="opacity:.75"><summary class="small mute">접힘 · 과제 정의·조사 지시가 아닌 글 (p=${Number(p.p).toFixed(2)}) · ${esc(p.text.replace(/\s+/g, " ").slice(0, 50))}…</summary><pre class="small" style="white-space:pre-wrap">${esc(p.text)}</pre></details>`).join("")
      : `<pre class="small" style="white-space:pre-wrap">${esc(idea.plan)}</pre>`;
    // A result Jev could not place (or one placed wrongly) gets a task picker; the plan's task list fills it.
    const assignSelect = (r, idea) => {
      const ids = Object.keys(idea.tasks || {});
      if (!ids.length || !(r.subtask_id === "?" || (r.assigned || "").startsWith("jev:"))) return "";
      return `<select data-iassign="${r.id}" aria-label="과제 고르기"><option value="">${r.subtask_id === "?" ? "미분류 · 과제 고르기" : "과제 바꾸기"}</option>${ids.map(t => `<option value="${esc(t)}">${esc(t)} ${esc(idea.tasks[t].title)}</option>`).join("")}</select>`;
    };
    // 압축 대기인 것은 눌러서 차례를 건너뛸 수 있다. 실행기가 1분 안에 집어 간다.
    const cstate = key => (i.compressing || {})[key];
    const compressPill = key => cstate(key) === "running" ? '<span class="pill warn">압축 중</span>'
      : cstate(key) === "queued" ? '<span class="pill warn">압축 요청됨</span>'
      : `<button class="pill warn pill-btn" data-icompress="${key}" title="차례를 기다리지 않고 지금 압축한다">압축 대기 · 지금 압축</button>`;
    const results = i.results.map(r => `<details class="idea-item"${r.latest ? "" : ' style="opacity:.6"'}><summary><span class="row">
      <b>${esc(r.subtask_id)}</b>${r.assigned ? `<span class="pill small" title="과제를 정한 방법">${esc(r.assigned === "ID" ? "ID로 확인" : r.assigned.startsWith("jev:") ? "Jev " + r.assigned.slice(4) : "직접 고름")}</span>` : ""}${r.latest ? "" : '<span class="pill">이전(덮어씀)</span>'}<span style="flex:1">${esc(r.subtask_title || (r.subtask_id === "?" ? "형식 밖 결과" : ""))}</span>
        ${r.status === "완료" ? "" : `<span class="pill warn">${esc(r.status || "상태 없음")}</span>`}
        <span class="small mute">${ago(r.created_at)}</span></span></summary>
      ${r.latest ? (r.summary ? `<pre class="small idea-text">${md(r.summary)}</pre>` : `<div class="row small mute">${compressPill("R" + r.id)}<span>곧 Codex가 짧게 정리한다</span></div>`) : ""}
      <details><summary>주장 ${r.claims.length}개 · 출처 없음 ${r.claims.filter(c => !c.source).length}</summary>${r.claims.map(claim).join("")}</details>
      <details><summary>원문 ${r.body.length.toLocaleString()}자 (보관용)</summary><pre class="small idea-text">${esc(r.body)}</pre></details>
      <div class="row idea-actions">${assignSelect(r, i)}<button class="danger" data-idel-result="${r.id}">결과 삭제</button></div></details>`);
    const taskName = m => m.task_id ? `${esc(m.task_id)} ${esc((i.tasks[m.task_id] || {}).title || "")}` : "자유 자료";
    const kindName = { paste: "붙여넣기", url: "링크", file: "파일" };
    const mats = i.materials.map(m => `<details class="idea-item"><summary><span class="row">
      <span style="flex:1;min-width:160px">${esc(m.title)}</span><span class="pill">${kindName[m.kind] || esc(m.kind)}</span>${m.task_id ? `<span class="pill">${taskName(m)}</span>` : ""}
      ${m.summary ? "" : compressPill("M" + m.id)}<span class="small mute">${ago(m.created_at)}</span></span></summary>
      ${m.url ? `<div class="small mute"><a href="${esc(m.url)}" target="_blank" rel="noopener">${esc(m.url)}</a></div>` : m.note ? `<div class="small mute">${esc(m.note)}</div>` : ""}
      ${m.summary ? `<pre class="small idea-text">${md(m.summary)}</pre>` : '<div class="small mute">곧 Codex가 짧게 정리한다. 종합·관제는 정리된 것만 읽는다.</div>'}
      <details><summary>원문 ${m.body.length.toLocaleString()}자 (보관용)</summary><pre class="small idea-text">${esc(m.body)}</pre></details>
      <div class="row idea-actions">
      ${others.length ? `<select data-imove="${m.id}" data-from="${esc(i.id)}" aria-label="다른 아이디어로 옮기기"><option value="">다른 아이디어로 옮기기</option>${others.map(o => `<option value="${esc(o.id)}">${esc(o.title)}</option>`).join("")}</select>` : ""}
      ${Object.keys(i.tasks || {}).length ? `<select data-imat="${m.id}" aria-label="과제 고르기"><option value="">과제 바꾸기</option><option value="-">자유 자료로</option>${Object.keys(i.tasks).map(t => `<option value="${esc(t)}">${esc(t)} ${esc(i.tasks[t].title)}</option>`).join("")}</select>` : ""}
      <button class="danger" data-idel-mat="${m.id}">자료 삭제</button></div></details>`);
    const fuLines = (i.followups || []).map(t => {
      const r = (t.runs || [])[0];
      const state = r ? (FSTATE[r.status] || esc(r.status)) : "차례 기다리는 중";
      const link = r && r.result_file ? ` · <a href="#/research-run/${encodeURIComponent(r.id)}">결과 보기</a>` : r && r.error ? ` · <span class="mute">${esc(r.error.slice(0, 60))}</span>` : "";
      return `<div style="display:block"><div class="small" style="white-space:pre-wrap">${esc(t.ask)}</div><div class="small mute">${state}${link} · ${ago(new Date((r ? r.started : t.created) * 1000))}${r && r.material_id ? " · 자유 자료로 들어감" : ""}</div></div>`;
    });
    // 정리본의 본문: Codex가 압축본으로 만든 종합. 원문은 아래 자료·결과에서 펼쳐 본다.
    const waiting = i.materials.filter(m => !m.summary).length + i.results.filter(r => r.latest && !r.summary).length;
    const synthCard = `<div class="card" style="margin-bottom:16px"><div class="row"><span class="t" style="flex:1">종합</span>${waiting ? `<span class="pill warn">압축 대기 ${waiting}</span>` : ""}${i.synth_at ? `<span class="small mute">${ago(i.synth_at)}</span>` : ""}</div>
      ${i.synth ? `<pre class="idea-text" style="margin-top:8px">${md(i.synth)}</pre>` : '<div class="small mute" style="margin-top:8px">아직 종합 전. 결과·자료가 압축되면 Codex가 이 아이디어 하나의 짧은 종합본을 만든다.</div>'}
      <div class="row" style="margin-top:10px"><button class="primary" data-icopy="overseer">관제에게 가져가기</button><button data-icopy="brief">정리본 복사</button></div></div>`;
    // 막 만든 아이디어: 할 일은 자료봉에 프롬프트를 주는 것뿐이라 그 버튼을 맨 위에 둔다.
    const fresh = !i.plan && !i.results.length;
    const promptCard = fresh ? `<div class="card" style="margin-bottom:16px"><div class="t">자료봉에게 줄 프롬프트</div>
      <div class="small mute" style="margin-top:6px">복사해서 자료봉에 붙인다. 자료봉 답은 아래 「자료봉 흐름」의 과제 쪼개기 답 칸에 붙인다.</div>
      <div class="row" style="margin-top:10px"><button class="primary" data-icopy="prompt" style="min-height:44px">전체 프롬프트 복사 (${i.prompt.length.toLocaleString()}자)</button></div></div>` : "";
    return `<h1>${esc(i.title)}</h1>
      <div class="sub">${ago(i.created_at)} 생성 · 자료 ${i.materials.length} · 결과 ${i.results.length}</div>
      ${i.candidate ? `<div class="card row" style="margin-bottom:12px"><span class="small" style="flex:1">새 아이디어 후보. 맞으면 확정하고, 아니면 맨 아래에서 삭제한다.</span><button data-iadopt="1">아이디어로 확정</button></div>` : ""}
      ${promptCard}${synthCard}
      <div class="idea-two">
      ${intakeForm([], i.id)}
      <div class="card">
        <div class="t">추가 조사</div>
        <textarea id="fu-text" rows="6" placeholder="대충 써도 된다. 예: 경쟁사 가격 더 / 일본에서도 되나 / B안 쪽으로" style="font-size:16px;margin-top:8px;width:100%">${esc(draft.get(i.id + ":fu"))}</textarea>
        <div class="row" style="margin-top:8px"><button class="primary" data-fu="run">Codex로 돌리기</button><button data-fu="copy">자료봉용 복사</button></div>
        <div id="fu-out" class="small" style="margin-top:8px"></div>
        ${fuLines.length ? `<details style="margin-top:8px"><summary>조사 이력 ${fuLines.length}</summary>${list(fuLines)}</details>` : ""}</div>
      </div>
      <h2>자료 (${i.materials.length})</h2>${list(mats)}
      <details style="margin-top:20px"${fresh ? " open" : ""}><summary style="min-height:44px"><b>자료봉 흐름</b> · 프롬프트 · 쪼개기 · 결과 붙여넣기 (결과 ${i.results.length})</summary>
      <h2>원문</h2><textarea rows="6" readonly style="font-size:16px">${esc(i.text)}</textarea>
      <h2>자료봉에게 줄 전체 프롬프트</h2>
      <div class="row" style="margin-bottom:8px"><button class="primary" data-icopy="prompt" style="min-height:44px">전체 프롬프트 복사</button></div>
      <details><summary>프롬프트 보기 (${i.prompt.length}자)</summary><pre class="small" style="white-space:pre-wrap">${esc(i.prompt)}</pre></details>
      <h2>과제 쪼개기 답</h2>
      ${i.plan ? `<details${i.results.length ? "" : " open"}><summary>저장됨 · ${ago(i.plan_at)} · ${i.plan.length}자</summary>${planView(i)}</details>${i.plans.slice(1).map(o => `<details><summary>이전 쪼개기 · ${ago(o.created_at)} · ${o.text.length}자</summary><pre class="small" style="white-space:pre-wrap">${esc(o.text)}</pre></details>`).join("")}` : ""}
      <form id="idea-plan" style="margin-top:8px"><textarea id="idea-plan-text" rows="6" placeholder="자료봉 답 전체 붙여넣기" style="font-size:16px">${esc(draft.get(i.id + ":plan") || i.plan)}</textarea>
        <div class="row" style="margin-top:8px"><button style="min-height:44px">${i.plan ? "바꿔 저장" : "저장"}</button></div></form>
      <h2>결과 붙여넣기</h2>
      <form id="idea-paste">${Array.from({ length: SLOTS }, (_, n) => `<textarea id="idea-slot-${n}" rows="4" placeholder="결과 ${n + 1}" style="margin-bottom:6px;font-size:16px">${esc(draft.get(slotKey(n)))}</textarea>`).join("")}
        <div class="row" style="margin-top:8px"><button class="primary" style="min-height:44px">결과 저장</button></div></form>
      <h2>결과 (${i.results.length})</h2>${list(results)}
      </details>
      <div class="small mute mono" style="margin-top:20px">정리본 ${esc(i.brief_path)}<br>원문 모음 ${esc(i.raw_path)}<br>${esc(i.id)}</div>
      <button class="danger" data-idel-idea="1" style="margin-top:12px">아이디어 삭제</button>`;
  };

  async function compressNow(b, base, key) {
    b.disabled = true;
    try { await api(`${base}/compress/${key}`, {}); }
    catch (err) { b.disabled = false; toast("실패: " + err.message); return; }
    b.textContent = "압축 요청됨"; toast("1분 안에 압축을 시작한다. 끝나면 화면이 바뀐다");
    const id = current.id, done = x => (key[0] === "M" ? x.materials : x.results).some(o => key[0] + o.id === key && o.summary);
    for (let n = 0; n < 90; n++) {   // 압축은 보통 1~3분. 15분까지 본다.
      await new Promise(r => setTimeout(r, 10000));
      if (location.hash !== "#/idea/" + encodeURIComponent(id)) return;
      const x = await api(`/api/ideas/${encodeURIComponent(id)}`).catch(() => null);
      if (!x) continue;
      if (done(x)) { toast("압축 끝"); AT.render(); return; }
      const live = document.querySelector(`[data-icompress="${key}"]`);
      if (live && (x.compressing || {})[key] === "running") live.textContent = "압축 중";
    }
  }

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
    if (d.icompress) { e.preventDefault(); compressNow(b, base, d.icompress); return; }   // 줄(details)을 펼치지 않는다
    try {
      if (d.fu) {
        const request = $("#fu-text").value.trim(); if (!request) { toast("요청을 한 줄 적는다"); return; }
        b.disabled = true;
        try {
          if (d.fu === "run") {
            await api(`${base}/followups`, { request }); draft.set(current.id + ":fu", ""); toast("조사 목록에 넣음. 곧 시작"); AT.render();
          } else {
            const r = await api(`${base}/followup/prompt`, { request });
            try { await navigator.clipboard.writeText(r.prompt); toast("복사함 (" + r.prompt.length + "자). 자료봉에 붙인다"); }
            catch {   // 복사 권한이 없는 브라우저: 글을 보여 주고 직접 복사하게 한다
              $("#fu-out").innerHTML = '<div class="mute">자동 복사가 막혀 있다. 아래 글을 전체 선택해 복사한다.</div><textarea id="fu-prompt" rows="8" readonly style="font-size:16px;width:100%"></textarea>';
              const t = $("#fu-prompt"); t.value = r.prompt; t.focus(); t.select();
            }
          }
        } finally { b.disabled = false; }
      } else if (d.iadopt) { await api(`${base}/adopt`, {}); toast("확정함"); AT.render(); }
      else if (d.idelMat) {
        if (!confirm("이 자료를 지운다. 되돌릴 수 없다.")) return;
        await api(`${base}/materials/${d.idelMat}`, undefined, "DELETE"); toast("자료 삭제함"); AT.render();
      } else if (d.icopy) copy(d.icopy === "prompt" ? current.prompt : d.icopy === "overseer"
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
  view.addEventListener("change", async e => {
    const mv = e.target.closest("select[data-imove]");   // 넣은 자료를 다른 아이디어로 옮긴다(홈·목록·아이디어 화면 어디서든)
    if (mv) {
      if (!mv.value) return;
      try {
        await api(`/api/ideas/${encodeURIComponent(mv.dataset.from)}/materials/${mv.dataset.imove}/move`, { idea_id: mv.value }, "PUT");
        toast("옮김: " + mv.options[mv.selectedIndex].text);
        if (location.hash.startsWith("#/idea/")) AT.render(); else { mv.closest("div.row").innerHTML = "<span>옮김 → <b>" + esc(mv.options[mv.selectedIndex].text) + "</b></span>"; }
      } catch (err) { toast("실패: " + err.message); }
      return;
    }
    const mat = e.target.closest("select[data-imat]");
    if (mat && current && mat.value) {
      try {
        await api(`/api/ideas/${encodeURIComponent(current.id)}/materials/${mat.dataset.imat}/subtask`, { subtask_id: mat.value === "-" ? "" : mat.value }, "PUT");
        toast("옮김"); AT.render();
      } catch (err) { toast("실패: " + err.message); }
      return;
    }
    const sel = e.target.closest("select[data-iassign]"); if (!sel || !current || !sel.value) return;
    try {
      await api(`/api/ideas/${encodeURIComponent(current.id)}/results/${sel.dataset.iassign}/subtask`, { subtask_id: sel.value }, "PUT");
      toast("과제 " + sel.value + "로 정함"); AT.render();
    } catch (err) { toast("실패: " + err.message); }
  });
  view.addEventListener("input", e => {
    const key = DRAFTED[e.target.id]?.(); if (key) draft.set(key, e.target.value);
  });
  view.addEventListener("submit", async e => {
    if (e.target.id === "idea-intake") {
      e.preventDefault();
      const text = $("#intake-text").value.trim(), picked = Array.from($("#intake-files").files);
      if (!text && !picked.length) { toast("붙여넣거나 파일을 고른다"); return; }
      const fixed = location.hash.startsWith("#/idea/") && current ? current.id : "";
      const out = $("#intake-result"), btn = e.target.querySelector("button"); btn.disabled = true; out.textContent = "넣는 중…";
      try {
        const files = await Promise.all(picked.map(readFile));
        const r = await api("/api/ideas/intake", { text, files, idea_id: fixed || ($("#intake-idea") || {}).value || "" });
        draft.set("intake:" + fixed, "");
        const all = await api("/api/ideas").catch(() => []);
        const lines = r.added.map(a => placedLine(a, all)).concat(r.skipped.map(x => `<div class="mute">건너뜀: ${esc(x)}</div>`));
        toast(r.added.length ? "넣음: " + r.added.length + "건" : "넣을 내용이 없었다");
        // 화면 이동 없이 결과를 그 자리에 보여 준다. 아이디어 화면이면 자료 목록을 새로 그리고 줄은 위에 남긴다.
        $("#intake-text").value = ""; $("#intake-files").value = "";
        if (fixed) { await AT.render(); const o = $("#intake-result"); if (o) o.innerHTML = lines.join(""); } else out.innerHTML = lines.join("");
      } catch (err) { out.textContent = ""; toast("실패: " + err.message); }
      finally { btn.disabled = false; }
    } else if (e.target.id === "idea-new") {
      e.preventDefault();
      const text = $("#idea-text").value.trim(); if (!text) return;
      try { const r = await api("/api/ideas", { title: $("#idea-title").value, text }); draft.set("new-title", ""); draft.set("new-text", ""); location.hash = "#/idea/" + encodeURIComponent(r.id); window.scrollTo(0, 0); toast("만듦. 맨 위 버튼으로 프롬프트를 복사한다"); }
      catch (err) { toast("실패: " + err.message); }
    } else if (e.target.id === "idea-plan" && current) {
      e.preventDefault();
      const text = $("#idea-plan-text").value.trim();
      if (text === current.plan) { draft.set(current.id + ":plan", ""); toast("바뀐 것 없음"); return; }
      // Empty clears the saved answer (kept in the history); before, an empty box could not be saved at all.
      if (!text && !confirm("저장된 과제 쪼개기 답을 비운다. 이전 것은 기록에 남는다.")) return;
      try { await api(`/api/ideas/${encodeURIComponent(current.id)}/plan`, { text }, "PUT"); draft.set(current.id + ":plan", ""); toast(text ? "과제 쪼개기 저장" : "과제 쪼개기 비움"); AT.render(); }
      catch (err) { toast("실패: " + err.message); }
    } else if (e.target.id === "idea-paste" && current) {
      e.preventDefault();
      const slots = Array.from({ length: SLOTS }, (_, n) => $("#idea-slot-" + n).value.trim()).filter(Boolean);
      if (!slots.length) return;
      try {
        const r = await api(`/api/ideas/${encodeURIComponent(current.id)}/results`, { slots });
        for (let n = 0; n < SLOTS; n++) draft.set(slotKey(n), "");
        toast("저장: " + r.added.map(a => a.subtask_id || "?").join(", ")); AT.render();
      } catch (err) { toast("실패: " + err.message); }
    }
  });
})();
