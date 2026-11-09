"use strict";
// olmuse 크레딧 쿠폰 만들기. 공개 사이트 장부에 바로 들어가고, 사용자는 크레딧 창 "쿠폰이 있어?"에 코드를 넣는다. API: console/coupons.py.
(() => {
  const { esc } = AT;
  AT.nav.push({ section: "olmuse", label: "쿠폰 만들기", href: "#/coupons", order: 85 });

  const ERRORS = { 409: "이미 있는 코드다", 400: "코드는 영문·숫자 6자 이상, 크레딧 1~1,000,000, 횟수 1~100,000" };

  AT.pages["/coupons"] = async () => {
    setTimeout(bind, 0);
    return `<h1>쿠폰 만들기</h1>
      <div class="sub">olmuse 공개 사이트 장부에 바로 만든다. 계정마다 한 번씩 쓸 수 있고, 코드는 영문·숫자만 남겨 대문자로 바뀐다.</div>
      <form id="coupon" class="card" style="display:grid;gap:10px;max-width:420px">
        <label>코드 <input name="code" required minlength="6" maxlength="64" autocomplete="off"></label>
        <label>크레딧 <input name="credits" type="number" min="1" max="1000000" required></label>
        <label>사용 횟수(서로 다른 계정 수) <input name="uses" type="number" min="1" max="100000" value="1" required></label>
        <button class="primary">만들기</button><div id="coupon-msg" class="small"></div>
      </form>`;
  };

  function bind() {
    const form = document.getElementById("coupon");
    if (!form) return;
    form.onsubmit = async e => {
      e.preventDefault();
      const f = new FormData(form), msg = document.getElementById("coupon-msg");
      const body = { code: f.get("code").trim(), credits: Number(f.get("credits")), uses: Number(f.get("uses")) };
      msg.textContent = "만드는 중…";
      const r = await fetch("/api/coupons", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
      if (r.status === 401) { location = "/login"; return; }
      const d = await r.json().catch(() => ({}));
      msg.innerHTML = r.ok
        ? `<span class="dot ok">만들었다 (200)</span> <b class="mono">${esc(d.code)}</b> · ${body.credits.toLocaleString()} 크레딧 · ${body.uses}회`
        : `<span style="color:var(--bad)">${r.status} · ${esc(ERRORS[r.status] || d.error || (typeof d.detail === "string" ? d.detail : "실패"))}</span>`;
    };
  }
})();
