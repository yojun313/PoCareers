/* 홈: 모집 기간 카드 + 필터 + 기업별 카드 목록. 데이터는 /api/postings 한 번. */

const VIEW_KEY = "ses_home_view";
const SORT_KEY = "ses_home_sort";
const POSTINGS_PER_CARD = 4;

const state = {
  data: null,
  period: "",          // jsSeq, ''=전체
  types: new Set(),
  regions: new Set(),
  dept: "",
  q: "",
  showClosed: false,
  sort: "deadline",
  view: "grid",
};

function regionOf(p) {
  return (p["근무지"] || "").split(" ")[0] || "기타";
}

function matches(p) {
  if (!state.showClosed && p.closed) return false;
  if (state.period && String(p.jsSeq) !== state.period) return false;
  if (state.types.size && !state.types.has(p["구분"])) return false;
  if (state.regions.size && !state.regions.has(regionOf(p))) return false;
  if (state.dept && !(p["선발학과"] || []).includes(state.dept)) return false;
  if (state.q) {
    const hay = [p["기관명"], p["부서명"], p["근무지"], p["직무명"], (p["선발학과"] || []).join(" "), p.period]
      .join(" ").toLowerCase();
    if (!state.q.split(/\s+/).every((t) => hay.includes(t))) return false;
  }
  return true;
}

function groupByCompany(postings) {
  const map = new Map();
  for (const p of postings) {
    const key = p.companySlug;
    if (!map.has(key)) map.set(key, { slug: key, name: p["기관명"], type: p["구분"], postings: [] });
    map.get(key).postings.push(p);
  }
  const groups = [...map.values()];
  for (const g of groups) {
    g.postings.sort((a, b) => (a.closed - b.closed) || String(a.deadlineIso).localeCompare(String(b.deadlineIso)));
    const open = g.postings.filter((p) => !p.closed);
    g.closed = open.length === 0;
    g.nextDeadline = (open[0] || g.postings[0]).deadlineIso || "9999";
    g.maxPay = Math.max(...g.postings.map((p) => payAmount(p["실습지원금"])));
    g.quota = g.postings.reduce((s, p) => s + (p["모집인원"] || 0), 0);
    // 지원자·경쟁률은 아직 접수 중인 공고만 셉니다 (마감 공고는 숫자가 멈춰 있음).
    const live = open.length ? open : g.postings;
    g.applicants = live.reduce((s, p) => s + (p.applicants || 0), 0);
    g.maxRatio = Math.max(0, ...live.map((p) => p.ratio || 0));
    g.delta = live.reduce((s, p) => s + (p.applicantsDelta24h || 0), 0);
    g.newest = g.postings.map((p) => p.firstSeen || "").sort().pop();
    g.isNew = g.postings.some((p) => p.isNew);
    g.regions = [...new Set(g.postings.map((p) => p["근무지"]).filter(Boolean))];
  }
  const by = {
    deadline: (a, b) => (a.closed - b.closed) || a.nextDeadline.localeCompare(b.nextDeadline),
    new: (a, b) => String(b.newest).localeCompare(String(a.newest)),
    pay: (a, b) => b.maxPay - a.maxPay,
    quota: (a, b) => b.quota - a.quota,
    applicants: (a, b) => (a.closed - b.closed) || b.applicants - a.applicants,
    ratio: (a, b) => (a.closed - b.closed) || b.maxRatio - a.maxRatio,
    name: (a, b) => a.name.localeCompare(b.name, "ko"),
  }[state.sort];
  return groups.sort((a, b) => by(a, b) || a.name.localeCompare(b.name, "ko"));
}

function renderPeriods() {
  const root = document.getElementById("period-cards");
  const all = state.data.postings.filter((p) => state.showClosed || !p.closed);
  const periods = state.data.periods.length
    ? state.data.periods
    : [...new Map(state.data.postings.map((p) => [p.jsSeq, { jsSeq: p.jsSeq, name: p.period, short: p.periodShort }])).values()];
  const card = (seq, label, name, count, extra) => `
    <button type="button" class="period-card ${state.period === seq ? "active" : ""}" data-period-card="${escapeHtml(seq)}">
      <span class="period-card-label">${label}</span>
      <span class="period-card-name">${escapeHtml(name)}</span>
      <span class="period-card-count"><b>${count}</b>건 ${extra || ""}</span>
    </button>`;
  root.innerHTML =
    card("", "모집 기간", "전체 기간", all.length,
      `· 기업 ${new Set(all.map((p) => p.companySlug)).size}곳`) +
    periods.map((pr) => {
      const list = all.filter((p) => String(p.jsSeq) === String(pr.jsSeq));
      const starts = list.map((p) => p.startDate).filter(Boolean).sort();
      const range = starts.length ? `· ${starts[0].slice(2).replaceAll("-", ".")} 시작` : "";
      return card(String(pr.jsSeq),
        `<span class="badge ${periodClass(pr.jsSeq)}">${escapeHtml(pr.short || pr.name)}</span>`,
        pr.name, list.length, range);
    }).join("");
  root.querySelectorAll("[data-period-card]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.period = btn.dataset.periodCard;
      render();
    });
  });
}

function renderChips(id, values, set) {
  const root = document.getElementById(id);
  root.innerHTML = values.map((v) =>
    `<button type="button" class="filter-chip ${set.has(v) ? "active" : ""}" data-v="${escapeHtml(v)}">${escapeHtml(v)}</button>`
  ).join("");
  root.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    set.has(b.dataset.v) ? set.delete(b.dataset.v) : set.add(b.dataset.v);
    render();
  }));
}

function companyCard(g) {
  const shown = g.postings.slice(0, POSTINGS_PER_CARD);
  const rows = shown.map((p) => {
    const b = deadlineBadge(p.deadlineIso, p.closed);
    const dates = p.startDate ? `${p.startDate.slice(2).replaceAll("-", ".")} ~ ${p.endDate.slice(2).replaceAll("-", ".")}` : p["실습기간"];
    return `
      <div class="company-posting-row ${p.closed ? "closed" : ""}">
        <span class="badge ${periodClass(p.jsSeq)}" title="${escapeHtml(p.period)}">${escapeHtml(p.periodShort || p.period)}</span>
        <span class="dept" title="${escapeHtml(p["부서명"])}">${escapeHtml(p["부서명"] || "부서 미지정")}
          <span class="dates">${escapeHtml(dates)}${p.weeks ? ` · ${p.weeks}주` : ""} · ${escapeHtml(p["실습지원금"] || "")}</span>
        </span>
        <span class="apply-chip ${p.ratio >= 1 ? "hot" : ""}" data-applicants-jid="${escapeHtml(p.jid)}"
          title="${escapeHtml(applicantsLabel(p))}${deltaText(p) ? " · " + deltaText(p) : ""}">
          <b>${p.applicants == null ? "-" : p.applicants}</b>/${p.quota || "-"}명
        </span>
        <span class="badge ${b.cls}" title="접수마감 ${escapeHtml(p["접수마감"])}">${b.text}</span>
      </div>`;
  }).join("");
  const more = g.postings.length > shown.length
    ? `<div class="company-more">외 ${g.postings.length - shown.length}건 더 보기</div>` : "";
  return `
    <a class="company-card ${g.closed ? "closed" : ""}" href="/company/${g.slug}">
      <div class="company-card-head">
        <div class="company-card-top">
          <div class="company-card-name">${escapeHtml(g.name)}</div>
          <div class="company-card-badges">
            ${g.isNew ? '<span class="badge badge-new">NEW</span>' : ""}
            <span class="badge badge-muted">${escapeHtml(g.type || "")}</span>
          </div>
        </div>
        <div class="company-card-meta"><span>${escapeHtml(g.regions.join(", "))}</span></div>
      </div>
      <div class="company-postings">${rows}${more}</div>
      <div class="company-card-foot">
        <span>공고 <b>${g.postings.length}</b>건 · 지원 <b>${g.applicants}</b> / 모집 <b>${g.quota}</b>명${
          g.delta ? ` <span class="apply-delta">+${g.delta}</span>` : ""}</span>
        <span>최대 <b>${g.maxPay ? g.maxPay.toLocaleString() + "원" : "-"}</b></span>
      </div>
    </a>`;
}

function render() {
  const d = state.data;
  renderPeriods();
  const pool = d.postings.filter((p) => state.showClosed || !p.closed);
  renderChips("type-chips", [...new Set(pool.map((p) => p["구분"]).filter(Boolean))].sort(), state.types);
  renderChips("region-chips", [...new Set(pool.map(regionOf))].sort(), state.regions);

  const list = d.postings.filter(matches);
  const groups = groupByCompany(list);
  document.getElementById("company-count").textContent = groups.length;
  document.getElementById("posting-count").textContent = `공고 ${list.length}건`;

  const root = document.getElementById("company-list");
  root.classList.toggle("view-list", state.view === "list");
  if (!d.postings.length) {
    root.innerHTML = `<div class="empty-state"><div class="icon">📭</div>
      아직 수집된 공고가 없습니다.<br />서버가 첫 점검을 마치면 이곳에 표시됩니다.</div>`;
  } else if (!groups.length) {
    root.innerHTML = `<div class="empty-state">조건에 맞는 공고가 없습니다.</div>`;
  } else {
    root.innerHTML = groups.map(companyCard).join("");
  }
  document.querySelectorAll("#view-toggle button").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === state.view));
}

function fillDeptSelect() {
  const depts = [...new Set(state.data.postings.flatMap((p) => p["선발학과"] || []))].sort((a, b) => a.localeCompare(b, "ko"));
  const sel = document.getElementById("dept-select");
  sel.innerHTML = '<option value="">전체 학과</option>' +
    depts.map((d) => `<option value="${escapeHtml(d)}">${escapeHtml(d)}</option>`).join("");
  sel.value = state.dept;
}

async function load() {
  try {
    state.data = await api.get("/api/postings");
  } catch (e) {
    document.getElementById("company-list").innerHTML =
      `<div class="empty-state">공고를 불러오지 못했습니다: ${escapeHtml(e.message)}</div>`;
    return;
  }
  renderMeta();
  fillDeptSelect();
  render();
  if (!watching) {
    watching = true;
    watchApplicants(state.data, async (_, changed) => {
      // 점검이 끝났으면 목록 전체를 다시 받습니다 (새 공고·마감도 같이 반영).
      try {
        state.data = await api.get("/api/postings");
      } catch (e) {
        return;
      }
      renderMeta();
      render();
      flashChanged(document, changed);
    });
  }
}

let watching = false;

function renderMeta() {
  const meta = document.getElementById("updated-meta");
  meta.innerHTML = state.data.updatedAt
    ? `<span class="live-dot" aria-hidden="true"></span>지원 현황 ${formatLocalTime(state.data.updatedAt)} 기준
       (<span data-time-ago="${escapeHtml(state.data.updatedAt)}">${timeAgo(state.data.updatedAt)}</span>)<br />
       <a href="https://ses.postech.ac.kr/student/manage/search/index.do" target="_blank" rel="noopener">SES에서 지원하기 &rarr;</a>`
    : "아직 수집 전";
}

// '몇 분 전' 글자가 멈춰 있지 않게
setInterval(() => {
  document.querySelectorAll("[data-time-ago]").forEach((el) => { el.textContent = timeAgo(el.dataset.timeAgo); });
}, 30000);

document.addEventListener("DOMContentLoaded", () => {
  try {
    state.view = localStorage.getItem(VIEW_KEY) || "grid";
    state.sort = localStorage.getItem(SORT_KEY) || "deadline";
  } catch (e) { /* 저장소를 못 쓰면 기본값 */ }
  const sortSel = document.getElementById("sort-select");
  sortSel.value = state.sort;
  sortSel.addEventListener("change", () => {
    state.sort = sortSel.value;
    try { localStorage.setItem(SORT_KEY, state.sort); } catch (e) { /* ignore */ }
    render();
  });
  document.querySelectorAll("#view-toggle button").forEach((b) => b.addEventListener("click", () => {
    state.view = b.dataset.view;
    try { localStorage.setItem(VIEW_KEY, state.view); } catch (e) { /* ignore */ }
    render();
  }));
  let timer = null;
  document.getElementById("q").addEventListener("input", (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => { state.q = e.target.value.trim().toLowerCase(); render(); }, 120);
  });
  document.getElementById("dept-select").addEventListener("change", (e) => { state.dept = e.target.value; render(); });
  document.getElementById("show-closed").addEventListener("change", (e) => { state.showClosed = e.target.checked; render(); });
  document.getElementById("filter-reset").addEventListener("click", () => {
    Object.assign(state, { period: "", dept: "", q: "", showClosed: false });
    state.types.clear();
    state.regions.clear();
    document.getElementById("q").value = "";
    document.getElementById("dept-select").value = "";
    document.getElementById("show-closed").checked = false;
    render();
  });
  const toggle = document.getElementById("filters-toggle");
  const body = document.getElementById("filters-body");
  toggle.addEventListener("click", () => {
    body.classList.toggle("open");
    toggle.textContent = body.classList.contains("open") ? "필터 닫기" : "필터 열기";
  });
  load();
  onPageRestore(load);
});
