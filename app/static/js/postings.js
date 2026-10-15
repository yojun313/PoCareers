/* 공고 화면들(홈·기업·캘린더·관리자)이 함께 쓰는 도우미. */

const KST_OFFSET_MS = 9 * 60 * 60 * 1000;

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* 모집 기간별 색 클래스. SES 탭 순서(SES_PERIODS)로 정하고, 이미 탭에서
   내려간 기간은 번호로 대신합니다 - 어느 화면에서든 같은 기간은 같은 색. */
function periodIndex(jsSeq) {
  const list = (typeof SES_PERIODS !== "undefined" && SES_PERIODS) || [];
  const i = list.findIndex((p) => String(p.jsSeq) === String(jsSeq));
  return (i >= 0 ? i : Number(jsSeq) || 0) % 3;
}
function periodClass(jsSeq) {
  return "period-" + periodIndex(jsSeq);
}

/* KST 기준 날짜 키 'YYYY-MM-DD'. 브라우저 시간대와 무관하게 SES(한국) 날짜로 셉니다. */
function kstDateKey(date) {
  return new Date(date.getTime() + KST_OFFSET_MS).toISOString().slice(0, 10);
}

function daysBetweenKeys(a, b) {
  return Math.round((Date.parse(b + "T00:00:00Z") - Date.parse(a + "T00:00:00Z")) / 86400000);
}

/* 마감 배지: {text, cls}. 'D-3' 이하는 빨갛게, 지난 건 '마감'. */
function deadlineBadge(deadlineIso, closed) {
  if (closed) return { text: "마감", cls: "badge-muted" };
  if (!deadlineIso) return { text: "마감일 미정", cls: "badge-outline" };
  const dl = new Date(deadlineIso);
  if (dl < new Date()) return { text: "마감", cls: "badge-muted" };
  const diff = daysBetweenKeys(kstDateKey(new Date()), kstDateKey(dl));
  if (diff === 0) return { text: "오늘 마감", cls: "badge-urgent" };
  return { text: "D-" + diff, cls: diff <= 3 ? "badge-urgent" : "badge-outline" };
}

function deadlineSentence(deadlineIso) {
  if (!deadlineIso) return "";
  const ms = new Date(deadlineIso) - new Date();
  if (ms < 0) return "접수 마감됨";
  const hours = Math.floor(ms / 3600000);
  if (hours < 48) return `${hours}시간 남음`;
  return `${Math.floor(hours / 24)}일 남음`;
}

/* '월 2,240,000원' -> 2240000 (정렬용). */
function payAmount(text) {
  const n = Number(String(text || "").replace(/[^\d]/g, ""));
  return Number.isFinite(n) ? n : 0;
}

function formatLocalTime(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  return d.toLocaleString("ko-KR", {
    month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function timeAgo(iso) {
  if (!iso) return "";
  const sec = Math.round((new Date() - new Date(iso)) / 1000);
  if (sec < 60) return "방금 전";
  if (sec < 3600) return `${Math.floor(sec / 60)}분 전`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}시간 전`;
  return `${Math.floor(sec / 86400)}일 전`;
}

/* 서버가 그린 화면(기업 페이지)의 data-* 자리표시를 채웁니다. */
function hydrateBadges(root) {
  (root || document).querySelectorAll("[data-period]").forEach((el) => {
    el.classList.add(periodClass(el.dataset.period));
  });
  (root || document).querySelectorAll("[data-deadline]").forEach((el) => {
    const b = deadlineBadge(el.dataset.deadline, el.dataset.closed === "1");
    el.textContent = b.text;
    el.classList.add(b.cls);
  });
  (root || document).querySelectorAll("[data-deadline-text]").forEach((el) => {
    el.textContent = deadlineSentence(el.dataset.deadlineText);
  });
  (root || document).querySelectorAll("[data-local-time]").forEach((el) => {
    if (el.dataset.localTime) el.textContent = (el.dataset.prefix || "") + formatLocalTime(el.dataset.localTime);
  });
}

/* ── 지원 현황 ─────────────────────────────────────── */

/* 지원자 수 한 줄 요약: '지원 12 / 모집 3'. 모르면 '-'. */
function applicantsLabel(p) {
  const n = p.applicants;
  const q = p.quota;
  return `지원 ${n == null ? "-" : n} / 모집 ${q || "-"}`;
}

/* 경쟁률 배지: {text, cls}. 모집보다 지원이 많으면 강조합니다. */
function ratioBadge(p) {
  if (p.ratio == null) return null;
  const text = p.ratio === 0 ? "지원 0" : `${p.ratio.toFixed(p.ratio < 10 ? 1 : 0)} : 1`;
  return { text, cls: p.ratio >= 1 ? "badge-hot" : "badge-outline" };
}

function deltaText(p) {
  const d = p.applicantsDelta24h;
  return d ? `24시간 ${d > 0 ? "+" : ""}${d}` : "";
}

/* 서버 점검이 끝날 때마다(스냅샷 updatedAt 이 바뀔 때) onChange(data, changedJids) 를
   부릅니다. 서버가 SES 를 다시 읽는 주기보다 자주 물어볼 필요는 없어서, 다음 점검
   예정 시각에 맞춰 묻고 최소 30초·최대 2분 간격으로 확인합니다. 탭이 숨어 있으면 쉽니다. */
function watchApplicants(initial, onChange) {
  let last = initial && initial.updatedAt;
  let known = {};
  (initial && initial.postings || []).forEach((p) => { known[p.jid] = p.applicants; });
  let timer = null;

  const schedule = (data) => {
    clearTimeout(timer);
    let wait = 60000;
    if (data && data.nextCheckAt) {
      // 점검은 1분 남짓 걸리니 예정 시각 조금 뒤에 확인
      wait = new Date(data.nextCheckAt) - new Date() + 20000;
    }
    timer = setTimeout(tick, Math.min(120000, Math.max(30000, wait)));
  };

  async function tick() {
    if (document.hidden) { schedule(null); return; }
    let data;
    try {
      data = await api.get("/api/applicants");
    } catch (e) {
      schedule(null);
      return;
    }
    if (data.updatedAt && data.updatedAt !== last) {
      last = data.updatedAt;
      const changed = Object.keys(data.applicants).filter((jid) =>
        jid in known && known[jid] !== data.applicants[jid].applicants);
      Object.entries(data.applicants).forEach(([jid, a]) => { known[jid] = a.applicants; });
      onChange(data, new Set(changed));
    }
    schedule(data);
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) { clearTimeout(timer); tick(); }
  });
  schedule(null);
}

/* 바뀐 숫자를 잠깐 반짝여서 갱신된 걸 알립니다. */
function flashChanged(root, changed) {
  changed.forEach((jid) => {
    (root || document).querySelectorAll(`[data-applicants-jid="${jid}"]`).forEach((el) => {
      el.classList.remove("flash");
      void el.offsetWidth; // 애니메이션 다시 시작
      el.classList.add("flash");
    });
  });
}
