/* 기업 페이지: 서버가 그린 배지에 색·D-day 를 채우고, 왼쪽 목록에 현재 보고 있는 공고를 표시.
   지원 현황은 서버 점검이 끝날 때마다 새로 받아 숫자만 바꿔 끼웁니다. */

function applySub(el, ratio, delta) {
  const parts = [];
  if (ratio !== "" && ratio != null) {
    const r = Number(ratio);
    parts.push(`경쟁률 ${r.toFixed(r < 10 ? 1 : 0)} : 1`);
  }
  if (delta) parts.push(`24시간 ${delta > 0 ? "+" : ""}${delta}`);
  el.textContent = parts.join(" · ");
}

/* 지원자 수 변화 계단 그래프 (SVG). 이력은 숫자가 바뀐 시점만 담겨 있습니다. */
function drawHistory(el) {
  let hist;
  try { hist = JSON.parse(el.dataset.history); } catch (e) { return; }
  const quota = Number(el.dataset.quota) || 0;
  const W = 600, H = 90, PAD = 6;
  const t0 = Date.parse(hist[0][0]);
  const t1 = Math.max(Date.now(), t0 + 1);
  const max = Math.max(1, quota, ...hist.map((h) => h[1]));
  const x = (t) => PAD + ((t - t0) / (t1 - t0)) * (W - 2 * PAD);
  const y = (n) => H - PAD - (n / max) * (H - 2 * PAD);
  let d = `M${x(t0)},${y(hist[0][1])}`;
  for (let i = 1; i < hist.length; i++) {
    const t = Date.parse(hist[i][0]);
    d += ` H${x(t)} V${y(hist[i][1])}`;
  }
  d += ` H${x(t1)}`;
  const quotaLine = quota
    ? `<line x1="${PAD}" x2="${W - PAD}" y1="${y(quota)}" y2="${y(quota)}" class="apply-history-quota" />` : "";
  const last = hist[hist.length - 1][1];
  el.innerHTML = `
    <div class="apply-history-head">
      <span>지원자 추이</span>
      <span>${formatLocalTime(hist[0][0])} ${hist[0][1]}명 &rarr; 현재 ${last}명${quota ? ` · 점선 = 모집 ${quota}명` : ""}</span>
    </div>
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="지원자 수 변화">
      ${quotaLine}
      <path d="${d}" class="apply-history-line" vector-effect="non-scaling-stroke" />
    </svg>`;
}

function renderUpdatedAt(iso) {
  document.querySelectorAll("[data-updated-at]").forEach((el) => {
    if (iso) el.dataset.updatedAt = iso;
    const at = el.dataset.updatedAt;
    el.innerHTML = at
      ? `<span class="live-dot" aria-hidden="true"></span>지원 현황 ${formatLocalTime(at)} 기준 (${timeAgo(at)})`
      : "";
  });
}

document.addEventListener("DOMContentLoaded", () => {
  hydrateBadges(document);
  document.querySelectorAll("[data-field=apply-sub]").forEach((el) =>
    applySub(el, el.dataset.ratio, Number(el.dataset.delta) || 0));
  document.querySelectorAll(".apply-history[data-history]").forEach(drawHistory);
  renderUpdatedAt();
  setInterval(() => renderUpdatedAt(), 30000);

  const facts = [...document.querySelectorAll(".fact-apply[data-applicants-jid]")];
  const updatedEl = document.querySelector("[data-updated-at]");
  const initial = {
    updatedAt: updatedEl ? updatedEl.dataset.updatedAt : null,
    postings: facts.map((el) => {
      const n = el.querySelector("[data-field=applicants]").textContent.trim();
      return { jid: el.dataset.applicantsJid, applicants: n === "-" ? null : Number(n) };
    }),
  };
  if (facts.length) {
    watchApplicants(initial, (data, changed) => {
      let total = 0;
      facts.forEach((el) => {
        const a = data.applicants[el.dataset.applicantsJid];
        if (!a) return;
        el.querySelector("[data-field=applicants]").textContent = a.applicants == null ? "-" : a.applicants;
        applySub(el.querySelector("[data-field=apply-sub]"), a.ratio, a.applicantsDelta24h);
        if (!el.closest(".posting-card.closed")) total += a.applicants || 0;
      });
      const hero = document.getElementById("hero-applicants");
      if (hero) hero.textContent = total;
      renderUpdatedAt(data.updatedAt);
      flashChanged(document, changed);
    });
  }

  const links = [...document.querySelectorAll("[data-nav-for]")];
  if (!links.length || !("IntersectionObserver" in window)) return;
  const byId = new Map(links.map((a) => [a.dataset.navFor, a]));
  const visible = new Set();
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => (e.isIntersecting ? visible.add(e.target.id) : visible.delete(e.target.id)));
    const first = links.find((a) => visible.has(a.dataset.navFor));
    links.forEach((a) => a.classList.toggle("active", a === first));
  }, { rootMargin: "-90px 0px -55% 0px" });
  byId.forEach((_, id) => {
    const el = document.getElementById(id);
    if (el) io.observe(el);
  });
});
