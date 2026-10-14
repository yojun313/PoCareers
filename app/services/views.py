"""스냅샷 -> 화면용 데이터 (기업별 묶음, 날짜 계산)."""

import hashlib
from datetime import date, datetime, timedelta, timezone

from app.services import store

KST = timezone(timedelta(hours=9))
NEW_DAYS = 3  # 처음 본 지 이 기간 안이면 NEW 표시


def company_slug(name: str) -> str:
    return hashlib.sha1((name or "").strip().encode("utf-8")).hexdigest()[:10]


def _deadline(text: str):
    """'2026-11-25 23:59' -> KST datetime."""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime((text or "").strip(), fmt).replace(tzinfo=KST)
        except ValueError:
            continue
    return None


def _weeks(start: str | None, end: str | None):
    if not start or not end:
        return None
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    return round(days / 7, 1)


def _detail_value(p: dict, label: str) -> str | None:
    for sec in p.get("detail") or []:
        for k, v in sec["rows"]:
            if k == label and v and v != "-":
                return v
    return None


def posting_view(p: dict) -> dict:
    """API/템플릿에 넘길 공고 한 건 (상세 포함 여부는 호출하는 쪽이 정함)."""
    now = datetime.now(KST)
    dl = _deadline(p.get("접수마감", ""))
    first = p.get("firstSeen")
    is_new = False
    if first:
        is_new = datetime.now(timezone.utc) - datetime.fromisoformat(first) < timedelta(
            days=NEW_DAYS
        )
    view = {
        k: v for k, v in p.items() if k not in ("detail", "rowSig", "detailFetchedAt")
    }
    view.update(
        {
            "companySlug": company_slug(p.get("기관명", "")),
            "deadlineIso": dl.isoformat() if dl else None,
            "closed": (not p.get("active", True)) or (dl is not None and dl < now),
            "isNew": is_new and p.get("active", True),
            "weeks": _weeks(p.get("startDate"), p.get("endDate")),
            "직무명": _detail_value(p, "직무명"),
            # 캘린더용 일정 (상세에만 있음). 예: '2026-12-02 00:00 (일정별도 협의)'
            "면접일자": _detail_value(p, "면접일자"),
            "최종선발일자": _detail_value(p, "최종선발일자"),
        }
    )
    return view


def all_postings(include_inactive: bool = True) -> list[dict]:
    snap = store.load_snapshot()
    items = [
        posting_view(p)
        for p in snap["postings"].values()
        if include_inactive or p.get("active", True)
    ]
    items.sort(
        key=lambda v: (v["closed"], v["deadlineIso"] or "9999", v.get("기관명", ""))
    )
    return items


def company(slug: str) -> dict | None:
    snap = store.load_snapshot()
    raw = [
        p
        for p in snap["postings"].values()
        if company_slug(p.get("기관명", "")) == slug
    ]
    if not raw:
        return None
    raw.sort(
        key=lambda p: (
            not p.get("active", True),
            p.get("접수마감", ""),
            p.get("부서명", ""),
        )
    )
    postings = []
    for p in raw:
        v = posting_view(p)
        v["detail"] = p.get("detail") or []
        v["detailFetchedAt"] = p.get("detailFetchedAt")
        postings.append(v)
    first = raw[0]
    return {
        "slug": slug,
        "name": first.get("기관명", ""),
        "type": first.get("구분", ""),
        "intro": next(
            (x for x in (_detail_value(p, "회사소개") for p in raw) if x), None
        ),
        "homepage": next(
            (x for x in (_detail_value(p, "홈페이지") for p in raw) if x), None
        ),
        "address": next(
            (x for x in (_detail_value(p, "근무지 주소") for p in raw) if x), None
        ),
        "postings": postings,
        "activeCount": sum(1 for v in postings if not v["closed"]),
        "updatedAt": snap["updatedAt"],
    }
