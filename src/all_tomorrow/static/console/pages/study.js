"use strict";
// 게임기획 공부: 달력은 날짜별 할 일, 커리큘럼은 전체 일정과 진도. 원본은 gamedesign-study, 콘솔은 읽기만. API: console/study.py.
(() => {
  const { esc, api } = AT;
  AT.nav.push({ section: "공부", label: "달력", href: "#/study-calendar", order: 50 },
              { section: "공부", label: "커리큘럼", href: "#/study-curriculum", order: 51 });
  AT.navAlias = Object.assign(AT.navAlias || {}, { "/study-day": "/study-calendar" });

  const LEARNERS = ["innollia", "pai"];
  const TYPE = { jam: "잼", review: "복기", study: "공부", analysis: "분석", rest: "휴식", buffer: "보강" };
  const STATE = {
    done: ["✓", "완료"], min: ["△", "최소판"], skipped: ["✕", "건너뜀"], rest: ["–", "휴식"], free: ["–", "자유"],
    missed: ["?", "기록 없음"], today: ["○", "오늘 할 일"], todo: ["·", "예정"],
  };
  const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];
  const pad = n => String(n).padStart(2, "0");
  const iso = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const md = date => `${+date.slice(5, 7)}/${+date.slice(8)}`;
  const today = () => iso(new Date());

  // 지난 날의 todo는 안 했다고 단정하지 않는다. 진도는 보고된 것만 적히기 때문이다.
  function state(day, who) {
    const s = day.progress[who].status;
    if (s !== "todo") return s;
    if (day.type === "rest") return "rest";
    if (day.type === "buffer") return "free";
    return day.date < today() ? "missed" : day.date === today() ? "today" : "todo";
  }
  const load = async () => (await api("/api/study")).days;
  const current = days => days.find(d => d.date >= today()) || days[days.length - 1];
  const chip = (day, who) => {
    const s = state(day, who);
    return `<span class="study-st ${s}" title="${who} ${STATE[s][1]}">${who[0].toUpperCase()} ${STATE[s][0]}</span>`;
  };
  const named = (day, who) => {
    const s = state(day, who);
    return `<span class="study-st ${s}">${STATE[s][0]} ${STATE[s][1]}</span>`;
  };
  const size = day => day.type === "jam" || !day.minutes ? "" : `${day.minutes}분`;   // 잼 날의 3은 분이 아니다
  const legend = `<div class="mute small study-legend">I innollia · P pai · ${["done", "min", "skipped", "missed", "today", "todo"].map(k => `${STATE[k][0]} ${STATE[k][1]}`).join(" · ")}</div>`;

  function detail(day) {
    const task = (label, text) => text ? `<dt>${esc(label)}</dt><dd>${esc(text)}</dd>` : "";
    const who = LEARNERS.map(name => {
      const p = day.progress[name];
      const done = p.date ? ` <span class="mute small">${md(p.date)} 기록${p.actual_min != null ? ` · ${p.actual_min}분` : ""}</span>` : "";
      return `<div><b>${name}</b> ${named(day, name)}${done}${p.note ? `<div class="mute small">${esc(p.note)}</div>` : ""}</div>`;
    }).join("");
    const links = (day.materials || []).map(m => {
      const title = /^https?:\/\//.test(m.url || "") ? `<a href="${esc(m.url)}" target="_blank" rel="noopener">${esc(m.title)}</a>` : esc(m.title);
      return `<li>${title}${m.login_required ? ` <span class="pill">로그인 필요</span>` : ""}${m.note ? `<div class="mute small">${esc(m.note)}</div>` : ""}</li>`;
    }).join("");
    const t = day.tasks || {};
    const sub = [md(day.date), day.weekday + "요일", TYPE[day.type] || day.type, size(day) && `${size(day)} (최소 ${day.min_version_minutes}분)`, day.weekly_review && "주간 리뷰"].filter(Boolean);
    return `<div class="card study-day"><div class="mute small">${esc(day.id)} · ${esc(sub.join(" · "))}</div><div class="t">${esc(day.theme)}</div>
      <dl>${task("같이", t.common)}${task("innollia", t.innollia)}${task("pai", t.pai)}</dl>
      ${links ? `<h2>자료</h2><ul class="study-links">${links}</ul>` : ""}
      <h2>진도</h2><div class="study-who">${who}</div></div>`;
  }

  async function calendar(arg) {
    const days = await load();
    if (!days.length) return `<h1>공부 달력</h1><div class="empty">계획이 비어 있다</div>`;
    const picked = days.find(d => d.id === arg) || current(days);
    const byDate = Object.fromEntries(days.map(d => [d.date, d]));
    const first = new Date(+picked.date.slice(0, 4), +picked.date.slice(5, 7) - 1, 1);
    const month = iso(first).slice(0, 7), last = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
    const months = [...new Set(days.map(d => d.date.slice(0, 7)))];
    const step = n => {
      const target = months[months.indexOf(month) + n];
      return target ? `<a class="pill" href="#/study-day/${esc(days.find(d => d.date.startsWith(target)).id)}">${+target.slice(5)}월</a>` : "";
    };
    const cells = Array.from({ length: first.getDay() }, () => `<div class="study-cell blank"></div>`);
    for (let n = 1; n <= last; n++) {
      const date = `${month}-${pad(n)}`, day = byDate[date];
      const mark = (date === today() ? " now" : "") + (day === picked ? " on" : "");
      cells.push(day ? `<a class="study-cell${mark} ${day.type}" href="#/study-day/${esc(day.id)}"><div class="row small"><b>${n}</b><span class="mute">${esc(day.id)}</span></div>
        <div class="study-theme">${esc(day.theme)}</div><div class="study-sts">${LEARNERS.map(w => chip(day, w)).join("")}</div></a>`
        : `<div class="study-cell${mark} off"><b class="small mute">${n}</b></div>`);
    }
    return `<h1>공부 달력</h1><div class="sub">날짜를 누르면 그날 할 일이 나온다</div>
      <div class="row study-month">${step(-1)}<b>${first.getFullYear()}년 ${first.getMonth() + 1}월</b>${step(1)}</div>
      <div class="study-cal">${WEEKDAYS.map(w => `<div class="study-head">${w}</div>`).join("")}${cells.join("")}</div>
      ${legend}${detail(picked)}`;
  }

  async function curriculum() {
    const days = await load();
    if (!days.length) return `<h1>커리큘럼</h1><div class="empty">계획이 비어 있다</div>`;
    const now = current(days), pass1 = days.filter(d => d.phase === "pass1" && d.type !== "rest");
    const did = (list, who) => list.filter(d => ["done", "min"].includes(state(d, who))).length;
    const missed = who => days.filter(d => state(d, who) === "missed").length;
    const stat = who => {
      const n = did(pass1, who), pct = Math.round(n / pass1.length * 100);
      return `<div class="card"><div class="mute small">${who} · 1회독</div><div class="stat">${n} / ${pass1.length}</div><div class="bar"><i style="width:${pct}%"></i></div><div class="mute small" style="margin-top:6px">기록 없는 지난 날 ${missed(who)}일</div></div>`;
    };
    const groups = [];
    for (const d of days) {
      const name = d.phase === "pre" ? "사전: 게임잼·복기" : d.phase === "pass1" ? `1회독 ${d.week}주차` : "보강·월간 리뷰";
      if (groups[groups.length - 1]?.name !== name) groups.push({ name, days: [] });
      groups[groups.length - 1].days.push(d);
    }
    const row = d => `<tr class="${d === now ? "now" : ""}"><td class="mono">${md(d.date)} ${esc(d.weekday)}</td><td class="mono">${esc(d.id)}</td>
      <td><a href="#/study-day/${esc(d.id)}">${esc(d.theme)}</a>${d.weekly_review ? ` <span class="pill">주간 리뷰</span>` : ""}</td>
      <td class="study-opt mute">${esc(TYPE[d.type] || d.type)}</td><td class="study-opt mute">${size(d)}</td>${LEARNERS.map(w => `<td>${chip(d, w)}</td>`).join("")}</tr>`;
    const section = g => {
      const count = g.days.filter(d => !["rest", "buffer"].includes(d.type));
      return `<h2>${esc(g.name)} <span class="mute small">${md(g.days[0].date)}~${md(g.days[g.days.length - 1].date)} · ${LEARNERS.map(w => `${w} ${did(count, w)}/${count.length}`).join(" · ")}</span></h2>
        <table class="study-table"><thead><tr><th>날짜</th><th>회차</th><th>주제</th><th class="study-opt">종류</th><th class="study-opt">분량</th><th>I</th><th>P</th></tr></thead><tbody>${g.days.map(row).join("")}</tbody></table>`;
    };
    return `<h1>커리큘럼</h1><div class="sub">${md(days[0].date)}~${md(days[days.length - 1].date)} · 진도는 디스코드 보고를 매니저가 기록한 것</div>
      <div class="grid"><a class="card" href="#/study-day/${esc(now.id)}"><div class="mute small">${now.date === today() ? "오늘" : "다음"} · ${md(now.date)} ${esc(now.weekday)} · ${esc(now.id)}</div><div class="t">${esc(now.theme)}</div></a>${LEARNERS.map(stat).join("")}</div>
      ${groups.map(section).join("")}${legend}`;
  }

  AT.pages["/study-calendar"] = () => calendar();
  AT.pages["/study-day/"] = calendar;
  AT.pages["/study-curriculum"] = curriculum;
})();
