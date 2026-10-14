/* 기업 페이지: 서버가 그린 배지에 색·D-day 를 채우고, 왼쪽 목록에 현재 보고 있는 공고를 표시. */
document.addEventListener("DOMContentLoaded", () => {
  hydrateBadges(document);

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
