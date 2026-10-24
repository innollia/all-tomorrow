"use strict";
(() => {
  const { esc, api } = AT;
  const labels = { ok: "확인됨", failed: "이상 관측", unknown: "미확인" };
  const placement = { must_local: "로컬 필수", movable: "AWS 이전 후보", aws: "AWS" };
  const scope = { local: "로컬", tailnet: "Tailnet", public: "공개" };
  const badge = s => `<span class="dot ${s === "ok" ? "ok" : s === "failed" ? "bad" : ""}">${labels[s]}</span>`;
  const move = s => `<span class="pill ${s.placement === "movable" ? "server-movable" : ""}">${placement[s.placement]}</span>`;
  const stamp = s => esc(new Date(s.checked_at).toLocaleString("ko-KR"));
  const href = s => `#/servers/${encodeURIComponent(s.id)}`;
  AT.nav.push({ section: "모니터링", label: "서버", href: "#/servers", order: 61 });
  AT.pages["/servers"] = async () => {
    const snap = await api("/api/servers");
    const names = Object.fromEntries(snap.hosts.map(h => [h.id, h.name]));
    const hosts = snap.hosts.map(h => `<article class="card server-host">
      <div class="row"><strong>${esc(h.name)}</strong>${badge(h.status)}</div>
      <div class="mute small">${esc(h.kind)} · ${esc(h.location)}</div>
      <div class="server-count"><b>${h.service_count}</b> 서비스 <span class="${h.failed_count ? "server-failed" : "mute"}">이상 ${h.failed_count}</span> <span class="mute">미확인 ${h.unknown_count}</span></div>
      <div class="mono">${esc(h.tailscale)}</div><div class="small mute">${h.always_on ? "상시 가동 예정" : "비상시 가동"} · ${esc(h.notes)}</div>
      <div class="server-host-links">${snap.services.filter(s => s.host_id === h.id).map(s => `<a href="${href(s)}">${esc(s.name)} ${badge(s.status)}</a>`).join("")}</div>
    </article>`).join("");
    const rows = snap.services.map(s => `<tr data-server="${esc(s.id)}" class="server-row">
      <td><a class="server-link" href="${href(s)}">${esc(s.name)}</a></td><td>${esc(s.description)}</td><td>${esc(names[s.host_id])}</td><td>${badge(s.status)}</td><td>${scope[s.scope]}</td><td>${move(s)}</td><td class="small mono">${stamp(s)}</td></tr>`).join("");
    return `<section class="servers"><h1>서버</h1><div class="sub">컴퓨터와 기능을 따로 봅니다. ${esc(snap.observed_from)}에서 관측 · 30초 캐시</div>
      <div class="server-notice">호스트 상태는 등록 서비스의 관측 요약입니다. ‘미확인’은 정상 판정이 아닙니다. 예약 대기는 현재 실행 중이라는 뜻이 아닙니다.</div>
      <h2 id="server-hosts">호스트 <span class="mute">${snap.hosts.length}</span></h2><div class="grid">${hosts || '<div class="empty">등록된 호스트 없음</div>'}</div>
      <h2>서비스 <span class="mute">${snap.services.length}</span></h2><div class="server-table" role="region" aria-label="서비스 목록 (가로 스크롤)" tabindex="0"><table><thead><tr><th>이름</th><th>기능</th><th>호스트</th><th>상태</th><th>공개 범위</th><th>배치</th><th>마지막 확인</th></tr></thead><tbody>${rows}</tbody></table>${rows ? "" : '<div class="empty">등록된 서비스 없음</div>'}</div></section>`;
  };
  AT.pages["/servers/"] = async id => {
    const snap = await api("/api/servers");
    const s = snap.services.find(s => s.id === id);
    if (!s) return '<h1>서비스 없음</h1><a href="#/servers">서버 목록으로</a>';
    const h = snap.hosts.find(h => h.id === s.host_id);
    const fields = [["기능", s.description], ["프로젝트", s.project], ["호스트", h.name], ["실행 방식", s.execution], ["포트", s.ports.join(" / ") || "없음"], ["공개 범위", scope[s.scope]], ["배치 이유", s.placement_reason], ["확인 방법", `${s.health.kind} · ${s.health.target || "없음"}`], ["관측 결과", s.detail], ["마지막 확인", new Date(s.checked_at).toLocaleString("ko-KR")]];
    return `<section class="servers"><a class="server-back" href="#/servers">← 서버 목록</a><h1>${esc(s.name)}</h1><div class="row server-detail-status">${badge(s.status)}${move(s)}</div><dl class="server-detail">${fields.map(([k,v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl><div class="server-notice">TCP·프로세스·예약 작업 확인은 기능 전체의 정상 동작을 보장하지 않습니다.</div></section>`;
  };
  document.addEventListener("click", e => {
    const row = e.target.closest("tr[data-server]");
    if (row && !e.target.closest("a") && !window.getSelection().toString()) location.hash = `/servers/${encodeURIComponent(row.dataset.server)}`;
  });
  AT.refresh["/servers"] = 30000;
})();
