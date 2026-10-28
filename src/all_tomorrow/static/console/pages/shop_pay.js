"use strict";
// 봉봉봉 입금: 주문 입금을 확인하면 상점 명예의 전당(innollia.github.io supporters_manual.json)에 올라가고 push된다. API: console/shop_pay.py.
(() => {
  const { esc, api, ago, list } = AT;
  AT.nav.push({ section: "봉봉봉", label: "입금 확인", href: "#/shop-pay", order: 80 });
  const won = n => Number(n).toLocaleString("ko-KR") + "원";

  AT.refresh["/shop-pay"] = 20000;  // Eve가 해금을 처리하면 상태가 바뀐다
  AT.pages["/shop-pay"] = async () => {
    const d = await api("/api/shop-pay");
    const dmState = o => { const r = (d.access || []).filter(x => x.order_id === o).pop();
      return !r ? "" : !r.done ? `<span class="pill warn">${r.action === "unlock" ? "해금" : "회수"} 대기</span>`
        : r.ok ? `<span class="pill">${r.state === "revoked" ? "회수됨" : "해금됨"}</span>` : `<span class="pill warn">실패 ${esc(r.error)}</span>`; };
    const pending = d.pending.map(p => `<div class="row"><span>${esc(p.name || "이름 없음")} · ${esc(String(p.amount))} ${esc(p.currency)}${p.live ? "" : ' <span class="pill warn">테스트</span>'}${p.note ? " · " + esc(p.note) : ""}</span>
      <span><button data-pick="${esc(p.id)}" data-name="${esc(p.name)}" data-note="${esc(p.note)}">이 후원으로 채우기</button> <button data-skip="${esc(p.id)}">대기에서 빼기</button></span></div>`);
    const paid = d.paid.slice().reverse().map(p => `<div class="row"><span><b class="mono">${esc(p.order_id)}</b> · ${esc(p.nickname)} · ${won(p.amount)} · ${p.method === "bank" ? "계좌" : "BMC"} · 공개 이름 ${esc(p.row.name)}${p.dm_user_id ? ` · DM <span class="mono">${esc(p.dm_user_id)}</span> ${dmState(p.order_id)} <button data-dm="unlock" data-o="${esc(p.order_id)}">해금</button> <button data-dm="revoke" data-o="${esc(p.order_id)}">회수</button>` : ""}</span>
      <span class="small mute">${ago(new Date(p.at))} · ${esc(p.commit)} <button class="danger" data-undo="${esc(p.order_id)}">되돌리기</button></span></div>`);
    setTimeout(bind, 0);
    return `<h1>봉봉봉 입금 확인</h1>
      <div class="sub">주문 스레드(주문번호 · 닉네임)의 입금을 확인하면 상점 명예의 전당에 한 줄이 올라가고 사이트 저장소에 push된다. 이메일·계좌 정보는 적지 않는다.</div>
      <form id="pay" class="card" style="display:grid;gap:8px;max-width:480px">
        <input name="order_id" placeholder="주문번호 (주문 스레드 제목 그대로)" required maxlength="40">
        <input name="nickname" placeholder="디스코드 닉네임" required>
        <input name="amount" type="number" min="1" placeholder="금액(원)" required>
        <select name="method"><option value="bank">계좌 이체</option><option value="bmc">Buy Me a Coffee</option></select>
        <input name="public_name" placeholder="명예의 전당 공개 이름 (비우면 익명)">
        <input name="note" placeholder="한마디 (공개, 선택)" maxlength="80">
        <input name="dm_user_id" placeholder="ss0 DM 해금 대상 디스코드 ID (해금이 든 주문만)" pattern="[0-9]*">
        <input name="pending_id" type="hidden">
        <button class="primary">입금 확인</button><div id="pay-msg" class="small"></div>
      </form>
      <h2>BMC 확인 대기</h2>${d.eve_error ? `<div class="small warn">Eve에서 못 받음: ${esc(d.eve_error)}</div>` : ""}${pending.length ? list(pending) : '<div class="empty">없음</div>'}
      <h2>확인한 입금</h2>${paid.length ? list(paid) : '<div class="empty">아직 없다.</div>'}`;
  };

  function bind() {
    const form = document.getElementById("pay");
    if (!form) return;
    form.onsubmit = async e => {
      e.preventDefault();
      const body = Object.fromEntries(new FormData(form));
      body.amount = Number(body.amount);
      const msg = document.getElementById("pay-msg");
      msg.textContent = "올리는 중…";
      try {
        const r = await api("/api/shop-pay", body);
        msg.textContent = `올렸다 (${r.commit}). 사이트 반영까지 1~2분.`;
        setTimeout(() => AT.render(), 800);
      } catch (err) { msg.textContent = "실패: " + (err.message || err); }
    };
    document.querySelectorAll("[data-pick]").forEach(b => b.onclick = () => {
      form.method.value = "bmc"; form.pending_id.value = b.dataset.pick;
      form.public_name.value = b.dataset.name; form.note.value = b.dataset.note; form.order_id.focus();
    });
    document.querySelectorAll("[data-dm]").forEach(b => b.onclick = async () => {
      await api(`/api/shop-pay/${encodeURIComponent(b.dataset.o)}/dm/${b.dataset.dm}`, {});
      AT.render();
    });
    document.querySelectorAll("[data-skip]").forEach(b => b.onclick = async () => {
      if (!confirm("이 후원을 확인 대기에서 뺄까? 명예의 전당에는 안 올라간다.")) return;
      await api(`/api/shop-pay/pending/${encodeURIComponent(b.dataset.skip)}`, undefined, "DELETE");
      AT.render();
    });
    document.querySelectorAll("[data-undo]").forEach(b => b.onclick = async () => {
      if (!confirm(`${b.dataset.undo} 확인을 되돌릴까? 명예의 전당에서 빠진다.`)) return;
      await api(`/api/shop-pay/${encodeURIComponent(b.dataset.undo)}`, undefined, "DELETE");
      AT.render();
    });
  }
})();
