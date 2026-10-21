/* 인턴 및 채용 공고: 분류 탭 + 검색 + 10건씩 페이지. 상태는 URL 쿼리에 둬서
   글을 보고 '목록'으로 돌아와도 보던 자리 그대로입니다. */

const PER_PAGE = 10;
const PAGER_SPAN = 5;

const state = { data: null, cat: "", field: "title", q: "", page: 1 };

function readQuery() {
  const u = new URLSearchParams(location.search);
  state.cat = u.get("cat") || "";
  state.field = ["title", "writer", "text"].includes(u.get("field")) ? u.get("field") : "title";
  state.q = u.get("q") || "";
  state.page = Math.max(1, parseInt(u.get("page"), 10) || 1);
}

function writeQuery() {
  const u = new URLSearchParams();
  if (state.cat) u.set("cat", state.cat);
  if (state.q) { u.set("field", state.field); u.set("q", state.q); }
  if (state.page > 1) u.set("page", state.page);
  const qs = u.toString();
  history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
}

function filtered() {
  const q = state.q.trim().toLowerCase();
  return state.data.posts.filter((p) => {
    if (state.cat && p.category !== state.cat) return false;
    if (q && !String(p[state.field] || "").toLowerCase().includes(q)) return false;
    return true;
  });
}

const ICON_FILE = `<svg class="board-ico" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-label="첨부파일"><path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/></svg>`;
const ICON_IMG = `<svg class="board-ico board-ico-img" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-label="본문 이미지"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>`;

function renderTabs() {
  const cats = ["", ...state.data.categories];
  // 보관함에 있는데 탭 목록에 없는 분류도 보여 줍니다
  state.data.posts.forEach((p) => { if (p.category && !cats.includes(p.category)) cats.push(p.category); });
  const root = document.getElementById("board-tabs");
  root.innerHTML = cats.map((c) => `
    <button type="button" role="tab" class="board-tab ${state.cat === c ? "active" : ""}" aria-selected="${state.cat === c}"
      data-cat="${escapeHtml(c)}">${state.cat === c ? '<span aria-hidden="true">&check;</span> ' : ""}${escapeHtml(c || "전체")}</button>`).join("");
  root.querySelectorAll("[data-cat]").forEach((b) => b.addEventListener("click", () => {
    state.cat = b.dataset.cat;
    state.page = 1;
    render();
  }));
}

function renderRows(list) {
  const rows = document.getElementById("board-rows");
  if (!state.data.posts.length) {
    rows.innerHTML = `<tr><td colspan="6" class="board-empty">아직 받아 온 글이 없습니다. 서버가 다음 점검 때 채웁니다.</td></tr>`;
    return;
  }
  if (!list.length) {
    rows.innerHTML = `<tr><td colspan="6" class="board-empty">검색 결과가 없습니다.</td></tr>`;
    return;
  }
  rows.innerHTML = list.map((p) => `
    <tr>
      <td class="c-no">${escapeHtml(p.no)}</td>
      <td class="c-cat">${escapeHtml(p.category)}</td>
      <td class="c-title">
        <a href="/board/${encodeURIComponent(p.artNo)}">
          <span class="board-row-title">${escapeHtml(p.title)}</span>${p.hasFile ? ICON_FILE : ""}${p.hasImage ? ICON_IMG : ""}${p.isNew ? '<span class="board-new" aria-label="새 글">N</span>' : ""}
        </a>
        <span class="board-row-meta">${escapeHtml(p.category)} · ${escapeHtml(p.writer)} · ${escapeHtml(p.date)}${p.views != null ? ` · 조회 ${p.views}` : ""}</span>
      </td>
      <td class="c-writer">${escapeHtml(p.writer)}</td>
      <td class="c-date">${escapeHtml(p.date)}</td>
      <td class="c-views">${p.views ?? "-"}</td>
    </tr>`).join("");
}

function renderPager(pages) {
  const root = document.getElementById("board-pager");
  if (pages <= 1) { root.innerHTML = ""; return; }
  const start = Math.floor((state.page - 1) / PAGER_SPAN) * PAGER_SPAN + 1;
  const end = Math.min(pages, start + PAGER_SPAN - 1);
  const btn = (page, label, aria, disabled) =>
    `<button type="button" class="board-page-btn" data-page="${page}" aria-label="${aria}" ${disabled ? "disabled" : ""}>${label}</button>`;
  let html = btn(1, "&laquo;", "처음", state.page === 1) +
    btn(Math.max(1, start - 1), "&lsaquo;", "이전", start === 1);
  for (let i = start; i <= end; i++) {
    html += `<button type="button" class="board-page-num ${i === state.page ? "active" : ""}" data-page="${i}"
      ${i === state.page ? 'aria-current="page"' : ""}>${i}</button>`;
  }
  html += btn(Math.min(pages, end + 1), "&rsaquo;", "다음", end === pages) +
    btn(pages, "&raquo;", "마지막", state.page === pages);
  root.innerHTML = html;
  root.querySelectorAll("[data-page]").forEach((b) => b.addEventListener("click", () => {
    state.page = Number(b.dataset.page);
    render();
    document.querySelector(".board-count-row").scrollIntoView({ block: "start", behavior: "smooth" });
  }));
}

function render() {
  const list = filtered();
  const pages = Math.max(1, Math.ceil(list.length / PER_PAGE));
  state.page = Math.min(state.page, pages);
  writeQuery();
  renderTabs();
  document.getElementById("board-count").textContent = list.length.toLocaleString();
  renderRows(list.slice((state.page - 1) * PER_PAGE, state.page * PER_PAGE));
  renderPager(pages);
}

async function load() {
  try {
    state.data = await api.get("/api/board");
  } catch (e) {
    document.getElementById("board-rows").innerHTML =
      `<tr><td colspan="6" class="board-empty">글을 불러오지 못했습니다: ${escapeHtml(e.message)}</td></tr>`;
    return;
  }
  const d = state.data;
  document.getElementById("board-meta").textContent = d.updatedAt
    ? `최근 ${d.posts.length}건 보관${d.total ? ` (게시판 전체 ${d.total.toLocaleString()}건)` : ""} · ${formatLocalTime(d.updatedAt)} 확인`
    : "";
  render();
}

document.addEventListener("DOMContentLoaded", () => {
  readQuery();
  document.getElementById("board-field").value = state.field;
  document.getElementById("board-q").value = state.q;
  document.getElementById("board-search").addEventListener("submit", (e) => {
    e.preventDefault();
    state.field = document.getElementById("board-field").value;
    state.q = document.getElementById("board-q").value.trim();
    state.page = 1;
    render();
  });
  load();
  onPageRestore(load);
});
