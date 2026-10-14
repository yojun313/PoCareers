/* 마감 캘린더: 공고의 접수마감(기본)·면접·최종선발·실습시작을 월 달력에 표시. */

const KINDS = [
  { key: "deadline", label: "접수마감", cls: "kind-deadline", on: true },
  { key: "interview", label: "면접", cls: "kind-interview", on: false },
  { key: "final", label: "최종선발", cls: "kind-final", on: false },
  { key: "start", label: "실습시작", cls: "kind-start", on: false },
];
const KIND_KEY = "ses_cal_kinds";
const MAX_PILLS = 3;
const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

const cal = {
  events: [],
  periods: [],
  kinds: new Set(KINDS.filter((k) => k.on).map((k) => k.key)),
  period: "",
  year: 0,
  month: 0, // 0-11
};

/* '2026-12-02 00:00 (일정별도 협의)' -> {date: '2026-12-02', time: '00:00', note: '일정별도 협의'} */
function parseSchedule(text) {
  const m = String(text || "").match(/(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{2}:\d{2}))?/);
  if (!m) return null;
  const note = (String(text).match(/\(([^)]*)\)\s*$/) || [])[1] || "";
  return { date: `${m[1]}-${m[2]}-${m[3]}`, time: m[4] && m[4] !== "00:00" ? m[4] : "", note };
}

function buildEvents(postings) {
  const out = [];
  for (const p of postings) {
    if (!p.active) continue; // SES 에서 내려간 공고는 달력에서 뺍니다
    const add = (kind, sched) => sched && out.push({ kind, ...sched, p });
    add("deadline", parseSchedule(p["접수마감"]));
    add("interview", parseSchedule(p["면접일자"]));
    add("final", parseSchedule(p["최종선발일자"]));
    if (p.startDate) add("start", { date: p.startDate, time: "", note: "" });
  }
  const order = Object.fromEntries(KINDS.map((k, i) => [k.key, i]));
  return out.sort((a, b) => a.date.localeCompare(b.date) || order[a.kind] - order[b.kind]
    || a.time.localeCompare(b.time) || a.p["기관명"].localeCompare(b.p["기관명"], "ko"));
}

function visibleEvents() {
  return cal.events.filter((e) => cal.kinds.has(e.kind) && (!cal.period || String(e.p.jsSeq) === cal.period));
}

const kindOf = (key) => KINDS.find((k) => k.key === key);
const pad = (n) => String(n).padStart(2, "0");

function renderChips() {
  const kindRoot = document.getElementById("cal-kind-chips");
  kindRoot.innerHTML = KINDS.map((k) => `<button type="button" class="filter-chip ${cal.kinds.has(k.key) ? "active" : ""}" data-kind="${k.key}">
      <span class="swatch ${k.cls}"></span>${k.label}</button>`).join("");
  kindRoot.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    cal.kinds.has(b.dataset.kind) ? cal.kinds.delete(b.dataset.kind) : cal.kinds.add(b.dataset.kind);
    try { localStorage.setItem(KIND_KEY, JSON.stringify([...cal.kinds])); } catch (e) { /* ignore */ }
    render();
  }));

  const perRoot = document.getElementById("cal-period-chips");
  perRoot.innerHTML = [{ jsSeq: "", short: "전체 기간" }, ...cal.periods].map((p) =>
    `<button type="button" class="filter-chip ${cal.period === String(p.jsSeq) ? "active" : ""}" data-period="${escapeHtml(p.jsSeq)}"
      title="${escapeHtml(p.name || "")}">${escapeHtml(p.short || p.name)}</button>`).join("");
  perRoot.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    cal.period = b.dataset.period;
    render();
  }));
}

function eventLine(e) {
  const k = kindOf(e.kind);
  const p = e.p;
  return `<a class="agenda-item" href="/company/${p.companySlug}#p-${p.jid}">
    <span class="badge ${k.cls}">${k.label}</span>
    <span class="badge ${periodClass(p.jsSeq)}">${escapeHtml(p.periodShort || "")}</span>
    <span class="name"><b>${escapeHtml(p["기관명"])}</b> · ${escapeHtml(p["부서명"] || "")}</span>
    <span class="time">${escapeHtml(e.time || "")}${e.note ? ` (${escapeHtml(e.note)})` : ""}</span>
  </a>`;
}

function dayBlock(dateKey, items, todayKey) {
  const d = new Date(dateKey + "T00:00:00Z");
  const diff = daysBetweenKeys(todayKey, dateKey);
  const rel = diff === 0 ? "오늘" : diff > 0 ? `D-${diff}` : `${-diff}일 전`;
  return `<div class="agenda-day ${diff < 0 ? "past" : ""}">
    <div class="agenda-date">${d.getUTCMonth() + 1}/${d.getUTCDate()} (${WEEKDAYS[d.getUTCDay()]})<small>${rel}</small></div>
    <div class="agenda-items">${items.map(eventLine).join("")}</div>
  </div>`;
}

function render() {
  renderChips();
  const { year, month } = cal;
  document.getElementById("cal-label").textContent = `${year}년 ${month + 1}월`;

  const byDate = new Map();
  for (const e of visibleEvents()) {
    if (!byDate.has(e.date)) byDate.set(e.date, []);
    byDate.get(e.date).push(e);
  }

  const todayKey = kstDateKey(new Date());
  const first = new Date(Date.UTC(year, month, 1));
  const startOffset = first.getUTCDay();
  const daysInMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const totalCells = Math.ceil((startOffset + daysInMonth) / 7) * 7;

  let html = "";
  for (let i = 0; i < totalCells; i++) {
    const d = new Date(Date.UTC(year, month, 1 - startOffset + i));
    const key = d.toISOString().slice(0, 10);
    const items = byDate.get(key) || [];
    const other = d.getUTCMonth() !== month;
    // 넘치면 "+N건" 줄이 들어갈 자리를 위해 알약을 하나 덜 그립니다.
    const shown = items.length > MAX_PILLS ? MAX_PILLS - 1 : items.length;
    const pills = items.slice(0, shown).map((e) =>
      `<span class="cal-page-pill ${kindOf(e.kind).cls}" title="${escapeHtml(kindOf(e.kind).label + " · " + e.p["기관명"] + " " + (e.p["부서명"] || ""))}">${escapeHtml(e.p["기관명"])}</span>`).join("");
    const dots = items.slice(0, 6).map((e) => `<span class="cal-dot ${kindOf(e.kind).cls}"></span>`).join("");
    html += `<button type="button" class="cal-page-cell ${other ? "other-month" : ""} ${key === todayKey ? "today" : ""}
        ${key < todayKey ? "past" : ""} ${items.length ? "has-events" : ""}" data-date="${key}" ${items.length ? "" : "tabindex='-1'"}>
      <span class="cal-page-cell-date">${d.getUTCDate()}</span>
      <span class="cal-page-pills">${pills}</span>
      ${items.length > shown ? `<span class="cal-page-more">+${items.length - shown}건 더</span>` : ""}
      <span class="cal-dots">${dots}</span>
    </button>`;
  }
  const grid = document.getElementById("cal-grid-root");
  grid.innerHTML = html;
  grid.querySelectorAll(".cal-page-cell.has-events").forEach((cell) => cell.addEventListener("click", () => {
    const key = cell.dataset.date;
    const d = new Date(key + "T00:00:00Z");
    document.getElementById("cal-day-title").textContent =
      `${d.getUTCMonth() + 1}월 ${d.getUTCDate()}일 (${WEEKDAYS[d.getUTCDay()]})`;
    document.getElementById("cal-day-body").innerHTML = dayBlock(key, byDate.get(key), todayKey);
    openDialog("cal-day-dialog");
  }));

  // 이달 일정 목록 - 모바일에서는 달력 칸에 점만 보이므로 이 목록이 본문입니다.
  const monthPrefix = `${year}-${pad(month + 1)}`;
  const monthKeys = [...byDate.keys()].filter((k) => k.startsWith(monthPrefix)).sort();
  const count = monthKeys.reduce((s, k) => s + byDate.get(k).length, 0);
  document.getElementById("agenda-title").textContent = `${month + 1}월 일정`;
  document.getElementById("agenda-count").textContent = count;
  document.getElementById("agenda-list").innerHTML = monthKeys.length
    ? monthKeys.map((k) => dayBlock(k, byDate.get(k), todayKey)).join("")
    : `<div class="agenda-empty">이달에는 표시할 일정이 없습니다.</div>`;
}

function shiftMonth(delta) {
  const d = new Date(Date.UTC(cal.year, cal.month + delta, 1));
  cal.year = d.getUTCFullYear();
  cal.month = d.getUTCMonth();
  render();
}

function goToday() {
  const key = kstDateKey(new Date());
  cal.year = Number(key.slice(0, 4));
  cal.month = Number(key.slice(5, 7)) - 1;
}

async function load() {
  let data;
  try {
    data = await api.get("/api/postings");
  } catch (e) {
    document.getElementById("cal-grid-root").innerHTML =
      `<div class="empty-state">공고를 불러오지 못했습니다: ${escapeHtml(e.message)}</div>`;
    return;
  }
  cal.periods = data.periods;
  cal.events = buildEvents(data.postings);
  render();
}

document.addEventListener("DOMContentLoaded", () => {
  try {
    const saved = JSON.parse(localStorage.getItem(KIND_KEY) || "null");
    if (Array.isArray(saved)) cal.kinds = new Set(saved);
  } catch (e) { /* 기본값 */ }
  document.getElementById("cal-weekdays").innerHTML = WEEKDAYS.map((w, i) =>
    `<div class="cal-page-weekday ${i === 0 ? "sun" : ""}">${w}</div>`).join("");
  goToday();
  document.getElementById("cal-prev").addEventListener("click", () => shiftMonth(-1));
  document.getElementById("cal-next").addEventListener("click", () => shiftMonth(1));
  document.getElementById("cal-today").addEventListener("click", () => { goToday(); render(); });
  load();
  onPageRestore(load);
});
