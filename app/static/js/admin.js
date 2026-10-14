/* 관리자: 수신자 추가/삭제/테스트 + 수집 상태. 점검 중에는 몇 초마다 상태를 다시 받습니다. */

let pollTimer = null;
let pendingRemove = null;

function statCard(label, value, sub, cls) {
  return `<div class="admin-stat-card ${cls || ""}">
    <div class="admin-stat-label">${label}</div>
    <div class="admin-stat-value">${value}</div>
    ${sub ? `<div class="admin-stat-sub">${sub}</div>` : ""}
  </div>`;
}

function renderStatus(s) {
  const sch = s.scheduler;
  document.getElementById("admin-stat-cards").innerHTML =
    statCard("진행 중 공고", s.activePostings, `기업 ${s.companies}곳`) +
    statCard("모집 기간", s.periods.length, s.periods.map((p) => escapeHtml(p.short)).join(" · ")) +
    statCard("메일 수신자", s.recipients.length, s.mailSender ? `발신 ${escapeHtml(s.mailSender)}` : "발신 계정 미설정",
      s.recipients.length && sch.mailEnabled ? "" : "danger") +
    statCard("마지막 점검", sch.lastCheckAt ? timeAgo(sch.lastCheckAt) : "-",
      sch.lastError ? "오류 발생" : (sch.lastOkAt ? "정상" : ""), sch.lastError ? "danger" : "");

  document.getElementById("recipient-count").textContent = s.recipients.length;
  document.getElementById("mail-sender").textContent = sch.mailEnabled
    ? `보내는 주소: ${s.mailSender}` : ".env 에 GMAIL_ADDRESS / GMAIL_APP_PASSWORD 가 없어 메일을 보낼 수 없습니다";
  const rows = document.getElementById("recipient-rows");
  rows.innerHTML = s.recipients.length
    ? s.recipients.map((e) => `<tr>
        <td class="admin-cell-strong">${escapeHtml(e)}</td>
        <td class="admin-col-actions"><span class="admin-row-actions">
          <button class="btn btn-ghost btn-sm" data-test="${escapeHtml(e)}" ${sch.mailEnabled ? "" : "disabled"}>테스트 메일</button>
          <button class="btn btn-ghost btn-sm admin-btn-danger" data-remove="${escapeHtml(e)}">삭제</button>
        </span></td></tr>`).join("")
    : `<tr><td colspan="2" class="admin-muted" style="padding: 24px 20px; text-align: center;">
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
    <dt>결과</dt><dd>${sum ? `공고 ${sum.total}건 · 신규 ${sum.new}건${sum.sent ? " · 메일 발송" : ""}` : "-"}</dd>
    <dt>데이터 갱신</dt><dd>${formatLocalTime(s.updatedAt)}</dd>`;
  const err = document.getElementById("status-error");
  err.hidden = !sch.lastError;
  err.textContent = sch.lastError || "";
  const btn = document.getElementById("check-now-btn");
  btn.disabled = !sch.running || sch.checking;
  btn.textContent = sch.checking ? "점검 중..." : "지금 점검";

  document.getElementById("period-rows").innerHTML = s.periods.length
    ? s.periods.map((p) => `<tr>
        <td><span class="badge ${periodClass(p.jsSeq)}">${escapeHtml(p.short)}</span> ${escapeHtml(p.name)}</td>
        <td class="admin-muted">${escapeHtml(p.jsSeq)}</td>
        <td class="num">${p.count}</td></tr>`).join("")
    : `<tr><td colspan="3" class="admin-muted" style="padding: 20px; text-align: center;">수집된 기간이 없습니다.</td></tr>`;

  clearTimeout(pollTimer);
  pollTimer = setTimeout(load, sch.checking ? 3000 : 30000);
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
