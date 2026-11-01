"use strict";
// 봉봉봉 재고·가격: 일시품절·시급·AI 사용료·할인율·고정가를 고치면 innollia.github.io stock.js에 쓰고 push된다. API: console/shop_stock.py.
(() => {
  const { esc, api } = AT;
  AT.nav.push({ section: "봉봉봉", label: "재고·가격", href: "#/shop-stock", order: 81 });

  AT.pages["/shop-stock"] = async () => {
    const d = await api("/api/shop-stock");
    const s = d.stock, ids = Object.keys(d.names);
    const box = (name, id, on) => `<label><input type="checkbox" name="${name}" value="${esc(id)}"${on ? " checked" : ""}> ${esc(d.names[id])}</label>`;
    const num = (name, label, v, max) => `<label>${label} <input name="${name}" type="number" min="0"${max ? ` max="${max}"` : ""} value="${esc(String(v ?? 0))}" required></label>`;
    setTimeout(bind, 0);
    return `<h1>봉봉봉 재고·가격</h1>
      <div class="sub">저장하면 상점 stock.js가 바뀌고 사이트 저장소에 push된다. 반영까지 1~2분.</div>
      <form id="stock" class="card" style="display:grid;gap:12px;max-width:560px">
        <div><b>일시품절</b><div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:4px">${ids.map(id => box("soldOut", id, s.soldOut.includes(id))).join("")}</div></div>
        <div style="display:grid;gap:6px">${num("labor", "시급(원)", s.labor)}${num("aiHour", "Claude 사용료(원/시간)", s.aiHour)}${num("aiSale", "AI 상품 할인율(%, 0이면 할인 없음)", s.aiSale, 100)}</div>
        <div><b>할인 받는 상품</b><div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:4px">${ids.map(id => box("aiItems", id, s.aiItems.includes(id))).join("")}</div></div>
        <div style="display:grid;gap:6px"><b>고정가</b>${d.fixed.map(id => num("price." + id, esc(d.names[id]) + "(원)", s.price[id])).join("")}</div>
        <button class="primary">저장 · 반영</button><div id="stock-msg" class="small"></div>
      </form>`;
  };

  function bind() {
    const form = document.getElementById("stock");
    if (!form) return;
    form.onsubmit = async e => {
      e.preventDefault();
      const f = new FormData(form), body = { soldOut: f.getAll("soldOut"), aiItems: f.getAll("aiItems"), price: {} };
      for (const k of ["labor", "aiHour", "aiSale"]) body[k] = Number(f.get(k));
      for (const [k, v] of f) if (k.startsWith("price.")) body.price[k.slice(6)] = Number(v);
      const msg = document.getElementById("stock-msg");
      msg.textContent = "올리는 중…";
      try {
        const r = await api("/api/shop-stock", body, "PUT");
        msg.textContent = r.unchanged ? "바뀐 것 없음." : `올렸다 (${r.commit}). 사이트 반영까지 1~2분.`;
      } catch (err) { msg.textContent = "실패: " + (err.message || err); }
    };
  }
})();
