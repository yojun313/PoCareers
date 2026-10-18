/* 관리자: 수신자 추가/삭제/테스트 + 수집 상태. 점검 중에는 몇 초마다 상태를 다시 받습니다. */

let pollTimer = null;
let pendingRemove = null;
let lastStatus = null;
let allPostings = null; // 관심 공고 선택 창을 처음 열 때 받습니다
const watchEdit = { email: null, selected: new Set() };

function statCard(label, value, sub, cls) {
  return `<div class="admin-stat-card ${cls || ""}">
    <div class="admin-stat-label">${label}</div>
    <div class="admin-stat-value">${value}</div>
    ${sub ? `<div class="admin-stat-sub">${sub}</div>` : ""}
  </div>`;
}

function renderStatus(s) {
  lastStatus = s;
  const sch = s.scheduler;
  document.getElementById("admin-stat-cards").innerHTML =
    statCard("진행 중 공고", s.activePostings, `기업 ${s.companies}곳`) +
    statCard("모집 기간", s.periods.filter((p) => !p.ended).length,
      s.periods.filter((p) => !p.ended).map((p) => escapeHtml(p.short)).join(" · ")) +
    statCard("메일 수신자", s.recipients.length,
      `SES ${s.recipients.filter((r) => r.ses).length}명 · 게시판 ${s.recipients.filter((r) => r.board).length}명`,
      s.recipients.length && sch.mailEnabled ? "" : "danger") +
    statCard("마지막 점검", sch.lastCheckAt ? timeAgo(sch.lastCheckAt) : "-",
      sch.lastError || sch.board.lastError ? "오류 발생" : (sch.lastOkAt ? "정상" : ""),
      sch.lastError || sch.board.lastError ? "danger" : "");

  document.getElementById("recipient-count").textContent = s.recipients.length;
  document.getElementById("mail-sender").textContent = sch.mailEnabled
    ? `보내는 주소: ${s.mailSender}` : ".env 에 GMAIL_ADDRESS / GMAIL_APP_PASSWORD 가 없어 메일을 보낼 수 없습니다";
  const rows = document.getElementById("recipient-rows");
  rows.innerHTML = s.recipients.length
    ? s.recipients.map((r) => `<tr>
        <td class="admin-cell-strong">${escapeHtml(r.email)}</td>
        ${["ses", "board"].map((kind) => `<td class="admin-col-switch">
          <label class="switch" title="${kind === "ses" ? "SES 현장실습 공고" : "인턴 및 채용 게시판"} 알림">
            <input type="checkbox" data-kind="${kind}" data-email="${escapeHtml(r.email)}" ${r[kind] ? "checked" : ""}
              aria-label="${escapeHtml(r.email)} ${kind === "ses" ? "SES 공고" : "인턴·채용 게시판"} 알림" />
            <span class="track"></span>
          </label></td>`).join("")}
        <td><button class="btn btn-ghost btn-sm watch-btn ${r.watch.length ? "on" : ""}" data-watch="${escapeHtml(r.email)}">
          ${r.watch.length ? `${r.watch.length}개` : "선택"}</button></td>
        <td class="admin-col-actions"><span class="admin-row-actions">
          <button class="btn btn-ghost btn-sm" data-test="${escapeHtml(r.email)}" ${sch.mailEnabled ? "" : "disabled"}>테스트 메일</button>
          <button class="btn btn-ghost btn-sm admin-btn-danger" data-remove="${escapeHtml(r.email)}">삭제</button>
        </span></td></tr>`).join("")
    : `<tr><td colspan="5" class="admin-muted" style="padding: 24px 20px; text-align: center;">
        등록된 수신자가 없습니다. 새 공고 알림을 받을 주소를 추가하세요.</td></tr>`;

  let dot = "ok", state = "대기 중";
  if (!sch.running) { dot = ""; state = "꺼짐 (--no-scheduler)"; }
  else if (sch.checking) { dot = "busy"; state = "점검 중..."; }
  else if (sch.lastError) { dot = "err"; state = "마지막 점검 실패"; }
  const sum = sch.lastSummary;
  document.getElementById("status-interval").textContent = `${sch.intervalMinutes}분마다 점검${sch.dryRun ? " · dry-run" : ""}`;
  document.getElementById("status-list").innerHTML = `
    <dt>상태</dt><dd><span class="status-dot ${dot}"></span>${state}</dd>
    <dt>마지막 점검</dt><dd>${formatLocalTime(sch.lastCheckAt)}</dd>
    <dt>마지막 성공</dt><dd>${formatLocalTime(sch.lastOkAt)}</dd>
    <dt>다음 점검</dt><dd>${sch.running && !sch.checking ? formatLocalTime(sch.nextCheckAt) : "-"}</dd>
    <dt>마감 직전 점검</dt><dd>${sch.nextDeadlineCheck
      ? `${formatLocalTime(sch.nextDeadlineCheck.at)} · ${escapeHtml(sch.nextDeadlineCheck.label)}${sch.nextDeadlineCheck.count > 1 ? ` 외 ${sch.nextDeadlineCheck.count - 1}건` : ""}`
      : "-"}</dd>
    <dt>SES 결과</dt><dd>${sum ? `공고 ${sum.total}건 · 신규 ${sum.new}건${sum.sent ? " · 메일 발송" : ""}${sum.watch ? ` · 관심 공고 지원자 증가 ${sum.watch}건` : ""}` : "-"}</dd>
    <dt>게시판 결과</dt><dd>${boardResult(sch.board)}</dd>
    <dt>데이터 갱신</dt><dd>${formatLocalTime(s.updatedAt)}</dd>`;
  const err = document.getElementById("status-error");
  const errors = [sch.lastError && `SES: ${sch.lastError}`, sch.board.lastError && `게시판: ${sch.board.lastError}`].filter(Boolean);
  err.hidden = !errors.length;
  err.textContent = errors.join("\n");
  const btn = document.getElementById("check-now-btn");
  btn.disabled = !sch.running || sch.checking;
  btn.textContent = sch.checking ? "점검 중..." : "지금 점검";

  document.getElementById("period-rows").innerHTML = s.periods.length
    ? s.periods.map((p) => `<tr>
        <td><span class="badge ${periodClass(p.jsSeq)}">${escapeHtml(p.short)}</span> ${escapeHtml(p.name)}
          ${p.ended ? `<span class="badge badge-muted">SES 에서 내려감</span>` : ""}</td>
        <td class="admin-muted">${escapeHtml(p.jsSeq)}</td>
        <td class="num">${p.ended ? "-" : p.count}</td></tr>`).join("")
    : `<tr><td colspan="3" class="admin-muted" style="padding: 20px; text-align: center;">수집된 기간이 없습니다.</td></tr>`;

  renderWatches(s.watches);
  renderMails(s.recentMails || []);

  clearTimeout(pollTimer);
  pollTimer = setTimeout(load, sch.checking ? 3000 : 30000);
}

function postingName(p) {
  return `${escapeHtml(p.기관명 || "")} · ${escapeHtml(p.부서명 || "")}`;
}

function renderWatches(watches) {
  document.getElementById("watch-count").textContent = watches.length;
  document.getElementById("watch-rows").innerHTML = watches.length
    ? watches.map((w) => `<tr class="${w.closed ? "watch-closed" : ""}">
        <td class="wrap">${w.found
          ? `<span class="badge ${periodClass(w.jsSeq)}">${escapeHtml(w.periodShort || "")}</span>
             <a class="admin-cell-strong" href="/company/${encodeURIComponent(w.companySlug)}">${postingName(w)}</a>
             ${w.closed ? `<span class="badge badge-muted">마감</span>` : ""}`
          : `<span class="admin-muted">사라진 공고 (${escapeHtml(w.jid)})</span>`}</td>
        <td class="num"><b>${w.applicants ?? "-"}</b> / ${w.quota ?? "-"}</td>
        <td class="num admin-hide-sm">${w.applicantsDelta24h ? `<span class="watch-delta">+${w.applicantsDelta24h}</span>` : "-"}</td>
        <td class="admin-hide-sm admin-muted">${w.applicantsChangedAt ? timeAgo(w.applicantsChangedAt) : "-"}</td>
        <td class="wrap admin-muted">${w.emails.map(escapeHtml).join(", ")}</td></tr>`).join("")
    : `<tr><td colspan="5" class="admin-muted" style="padding: 20px; text-align: center;">
        관심 공고가 없습니다. 메일 수신자 표의 <b>관심 공고</b>에서 고르세요.</td></tr>`;
}

async function openWatchDialog(email) {
  const r = lastStatus.recipients.find((x) => x.email === email);
  if (!r) return;
  watchEdit.email = email;
  watchEdit.selected = new Set(r.watch);
  document.getElementById("watch-email").textContent = `${email} 이(가) 지원자 증가 알림을 받을 공고`;
  document.getElementById("watch-search").value = "";
  document.getElementById("watch-only").checked = false;
  openDialog("watch-dialog");
  if (!allPostings) {
    document.getElementById("watch-list").innerHTML = `<div class="empty-state"><span class="spinner"></span></div>`;
    try {
      allPostings = (await api.get("/api/postings")).postings;
    } catch (err) {
      showSnackbar(err.message, "error");
      return;
    }
  }
  renderWatchList();
}

function renderWatchList() {
  const q = document.getElementById("watch-search").value.trim().toLowerCase();
  const only = document.getElementById("watch-only").checked;
  // 진행 중인 공고 + 이미 고른 공고(마감됐어도 해제할 수 있게)
  const items = allPostings.filter((p) =>
    (!p.closed || watchEdit.selected.has(p.jid)) &&
    (!only || watchEdit.selected.has(p.jid)) &&
    (!q || [p.기관명, p.부서명, p.직무명].some((x) => (x || "").toLowerCase().includes(q))));
  document.getElementById("watch-list").innerHTML = items.length
    ? items.map((p) => `<label class="watch-item">
        <input type="checkbox" data-jid="${escapeHtml(p.jid)}" ${watchEdit.selected.has(p.jid) ? "checked" : ""} />
        <span class="watch-item-body">
          <span class="watch-item-title"><span class="badge ${periodClass(p.jsSeq)}">${escapeHtml(p.periodShort || "")}</span> ${postingName(p)}</span>
          <span class="watch-item-sub">${p.직무명 ? `${escapeHtml(p.직무명)} · ` : ""}지원 ${p.applicants ?? "-"} / 모집 ${p.quota ?? "-"}${p.closed ? " · 마감" : ""}</span>
        </span></label>`).join("")
    : `<div class="admin-muted" style="padding: 24px; text-align: center;">조건에 맞는 공고가 없습니다.</div>`;
  document.getElementById("watch-selected").textContent = `${watchEdit.selected.size}개 선택`;
}

const MAIL_KINDS = { ses: "SES 공고", board: "인턴·채용", watch: "관심 공고", startup: "시작 알림", test: "테스트" };

function renderMails(mails) {
  document.getElementById("mail-rows").innerHTML = mails.length
    ? mails.map((m) => `<tr>
        <td class="admin-muted">${formatLocalTime(m.at)}</td>
        <td><span class="badge badge-muted">${escapeHtml(MAIL_KINDS[m.kind] || m.kind)}</span></td>
        <td class="wrap">${escapeHtml(m.subject)}</td>
        <td class="wrap admin-muted admin-hide-sm">${m.to.map(escapeHtml).join(", ")}</td>
        <td>${m.ok ? "발송" : `<span class="admin-btn-danger" title="${escapeHtml(m.error || "")}">실패</span>`}</td></tr>`).join("")
    : `<tr><td colspan="5" class="admin-muted" style="padding: 20px; text-align: center;">보낸 메일이 없습니다.</td></tr>`;
}

function boardResult(b) {
  if (!b.enabled) return "꺼짐 (.env BOARD_ENABLED=false)";
  if (!b.lastSummary) return b.lastError ? "실패" : "-";
  return `새 글 ${b.lastSummary.new}건${b.lastSummary.sent ? " · 메일 발송" : ""}`;
}

async function load() {
  try {
    renderStatus(await api.get("/api/admin/status"));
  } catch (e) {
    if (e.status === 401) window.location.href = "/sign-in";
    else showSnackbar(e.message, "error");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("recipient-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("recipient-email");
    try {
      await api.post("/api/admin/recipients", { email: input.value });
      showSnackbar(`${input.value} 을(를) 추가했습니다.`, "success");
      input.value = "";
      load();
    } catch (err) {
      showSnackbar(err.message, "error");
    }
  });

  document.getElementById("recipient-rows").addEventListener("click", async (e) => {
    const watch = e.target.closest("[data-watch]");
    if (watch) return openWatchDialog(watch.dataset.watch);
    const test = e.target.closest("[data-test]");
    const remove = e.target.closest("[data-remove]");
    if (test) {
      test.disabled = true;
      test.textContent = "보내는 중...";
      try {
        await api.post("/api/admin/recipients/test", { email: test.dataset.test });
        showSnackbar("테스트 메일을 보냈습니다.", "success");
      } catch (err) {
        showSnackbar(err.message, "error");
      }
      test.disabled = false;
      test.textContent = "테스트 메일";
    } else if (remove) {
      pendingRemove = remove.dataset.remove;
      document.getElementById("remove-email").textContent = pendingRemove;
      openDialog("remove-dialog");
    }
  });

  document.getElementById("recipient-rows").addEventListener("change", async (e) => {
    const input = e.target.closest("input[data-kind]");
    if (!input) return;
    const label = input.dataset.kind === "ses" ? "SES 공고" : "인턴·채용 게시판";
    input.disabled = true;
    try {
      await api.patch("/api/admin/recipients", { email: input.dataset.email, [input.dataset.kind]: input.checked });
      showSnackbar(`${input.dataset.email}: ${label} 알림 ${input.checked ? "켬" : "끔"}`, "success");
    } catch (err) {
      input.checked = !input.checked;
      showSnackbar(err.message, "error");
    }
    input.disabled = false;
  });

  document.getElementById("watch-search").addEventListener("input", renderWatchList);
  document.getElementById("watch-only").addEventListener("change", renderWatchList);
  document.getElementById("watch-list").addEventListener("change", (e) => {
    const input = e.target.closest("input[data-jid]");
    if (!input) return;
    if (input.checked) watchEdit.selected.add(input.dataset.jid);
    else watchEdit.selected.delete(input.dataset.jid);
    document.getElementById("watch-selected").textContent = `${watchEdit.selected.size}개 선택`;
  });
  document.getElementById("watch-save").addEventListener("click", async (e) => {
    e.target.disabled = true;
    try {
      await api.patch("/api/admin/recipients", { email: watchEdit.email, watch: [...watchEdit.selected] });
      showSnackbar(`${watchEdit.email}: 관심 공고 ${watchEdit.selected.size}개 저장`, "success");
      closeDialog("watch-dialog");
      load();
    } catch (err) {
      showSnackbar(err.message, "error");
    }
    e.target.disabled = false;
  });

  document.getElementById("remove-confirm").addEventListener("click", async () => {
    try {
      await api.del("/api/admin/recipients", { email: pendingRemove });
      showSnackbar("삭제했습니다.");
      closeDialog("remove-dialog");
      load();
    } catch (err) {
      showSnackbar(err.message, "error");
    }
  });

  document.getElementById("check-now-btn").addEventListener("click", async () => {
    try {
      await api.post("/api/admin/check");
      showSnackbar("점검을 시작합니다. 1~2분 정도 걸립니다.");
      setTimeout(load, 1500);
    } catch (err) {
      showSnackbar(err.message, "error");
    }
  });

  load();
});
