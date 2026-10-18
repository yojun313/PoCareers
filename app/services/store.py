"""저장소: MongoDB 에 공고 보관함, 게시판 보관함, 수신자, 알림/점검 기록을 둡니다.

컬렉션 구성은 app/core/db.py 참고. 스케줄러 스레드가 쓰고 웹 서버가 읽습니다
(pymongo 클라이언트는 스레드끼리 같이 써도 됩니다).

웹 화면은 요청마다 공고 전체를 읽으므로, 읽은 결과를 메모리에 두고 meta 의
version 이 바뀔 때만 다시 읽습니다. 쓰는 쪽은 쓰고 나서 version 을 올립니다 -
`run.py --once` 처럼 다른 프로세스가 써도 웹 서버가 알아챕니다.

DB 안에서는 시각을 datetime 으로, 밖으로 내줄 때는 지금까지처럼 ISO 문자열로
바꿉니다 (views/템플릿/JS 는 문자열을 기대합니다).
"""

import json
import re
import shutil
import threading
from datetime import datetime, timedelta, timezone

from pymongo import ReplaceOne, UpdateOne
from pymongo.errors import DuplicateKeyError

from app.config import BOARD_EXCLUDE, LEGACY_FILES, STATE_DIR
from app.core.db import (
    board_posts_col,
    check_log_col,
    ensure_indexes,
    mail_log_col,
    meta_col,
    notified_col,
    periods_col,
    posting_changes_col,
    postings_col,
    recipients_col,
    watches_col,
)

_lock = threading.RLock()
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def now_iso() -> str:
    return utcnow().isoformat(timespec="seconds")


def _iso(value):
    """DB 값 -> 화면용. datetime 은 ISO 문자열로 (안쪽 dict/list 까지)."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="seconds")
    if isinstance(value, dict):
        return {k: _iso(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_iso(v) for v in value]
    return value


def _dt(value) -> datetime | None:
    """ISO 문자열(예전 JSON) -> datetime."""
    if isinstance(value, datetime) or value is None:
        return value
    try:
        d = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _bump(kind: str, **fields) -> None:
    """meta 갱신 + version 증가 (웹 서버 캐시를 무효화)."""
    update = {"$inc": {"version": 1}}
    if fields:
        update["$set"] = fields
    meta_col.update_one({"_id": kind}, update, upsert=True)


def _version(kind: str):
    doc = meta_col.find_one({"_id": kind}, {"version": 1})
    return doc.get("version") if doc else None


def _label(p: dict) -> str:
    return f"{p.get('기관명', '')} / {p.get('부서명', '')}"


# ── SES 공고 ────────────────────────────────────────

# 문서 안 필드 순서 (Compass 에서 위에서부터 읽기 좋게). 목록 값 -> 상태 -> 상세 -> 이력.
_ROW_ORDER = (
    "jid",
    "기관명",
    "부서명",
    "구분",
    "근무지",
    "실습기간",
    "접수마감",
    "deadlineAt",
    "선발학과",
    "참여인원",
    "모집인원",
    "실습지원금",
    "startDate",
    "endDate",
    "jsSeq",
    "period",
    "periodShort",
)
_META_ORDER = (
    "active",
    "firstSeen",
    "lastSeen",
    "removedAt",
    "finalCheck",
    "detailFetchedAt",
    "rowSig",
    "detail",
    "applicantsHistory",
)
# 바뀌면 posting_changes 에 남길 목록 값 (지원자 수는 applicantsHistory 에 따로)
_TRACKED = (
    "기관명",
    "부서명",
    "구분",
    "근무지",
    "실습기간",
    "접수마감",
    "선발학과",
    "모집인원",
    "실습지원금",
    "jsSeq",
    "period",
)

_snapshot_cache = {"version": object(), "data": None}


def _posting_out(doc: dict) -> dict:
    p = _iso({k: v for k, v in doc.items() if k != "_id"})
    p["applicantsHistory"] = [
        [h["at"], h["count"]] for h in p.get("applicantsHistory") or []
    ]
    return p


def load_snapshot() -> dict:
    """{"updatedAt", "periods", "postings": {jid: posting}}. DB 가 바뀔 때만 다시 읽습니다."""
    with _lock:
        version = _version("ses")
        if _snapshot_cache["version"] != version or _snapshot_cache["data"] is None:
            meta = meta_col.find_one({"_id": "ses"}) or {}
            data = {
                "updatedAt": _iso(meta.get("updatedAt")),
                "periods": load_periods(),
                "postings": {d["_id"]: _posting_out(d) for d in postings_col.find()},
            }
            _snapshot_cache.update(version=version, data=data)
        return _snapshot_cache["data"]


def _ordered(item: dict) -> dict:
    out = {"_id": item["jid"]}
    for k in _ROW_ORDER:
        if k in item:
            out[k] = item[k]
    for k, v in item.items():
        if k not in out and k not in _META_ORDER:
            out[k] = v
    for k in _META_ORDER:
        if k in item:
            out[k] = item[k]
    return out


def _deadline_at(text: str) -> datetime | None:
    from app.services.views import _deadline  # 순환 import 방지

    d = _deadline(text or "")
    return d.astimezone(timezone.utc) if d else None


def merge_snapshot(fetched: dict) -> None:
    """새로 받은 목록을 보관함에 합칩니다.

    - 목록에 있는 공고: 목록 값 갱신, 상세는 새로 받은 게 있을 때만 교체
    - 목록에서 사라진 공고: 지우지 않고 active=False (웹에서 "마감" 으로 표시)
    - 목록 값이 바뀌면 posting_changes 에 바뀐 값을 남깁니다
    """
    with _lock:
        old = {d["_id"]: d for d in postings_col.find()}
        now = utcnow()
        ops, changes, current = [], [], set()
        for row in fetched["rows"]:
            jid = row["jid"]
            current.add(jid)
            prev = old.get(jid, {})
            item = {k: v for k, v in row.items() if k != "legacyKey"}
            item["deadlineAt"] = _deadline_at(row.get("접수마감"))
            item["active"] = True
            item["firstSeen"] = prev.get("firstSeen", now)
            item["lastSeen"] = now
            if prev.get("finalCheck"):
                item["finalCheck"] = prev["finalCheck"]
            if jid in fetched["details"]:
                item["detail"] = fetched["details"][jid]
                item["detailFetchedAt"] = now
            else:
                item["detail"] = prev.get("detail")
                item["detailFetchedAt"] = prev.get("detailFetchedAt")
            # 목록 값이 바뀌면 다음 점검 때 상세도 다시 받도록 지문을 남깁니다.
            item["rowSig"] = _row_sig(row)
            item["applicantsHistory"] = _push_applicants(
                prev.get("applicantsHistory"), row, now
            )
            diff = {
                k: {"before": prev.get(k), "after": item.get(k)}
                for k in _TRACKED
                if prev and prev.get(k) != item.get(k)
            }
            if prev and not prev.get("active", True):
                diff["active"] = {"before": False, "after": True}  # SES 에 다시 올라옴
            if diff:
                changes.append(
                    {"jid": jid, "공고": _label(item), "at": now, "changes": diff}
                )
            ops.append(ReplaceOne({"_id": jid}, _ordered(item), upsert=True))
        for jid, prev in old.items():
            if jid not in current and prev.get("active", True):
                ops.append(
                    UpdateOne(
                        {"_id": jid}, {"$set": {"active": False, "removedAt": now}}
                    )
                )
                changes.append(
                    {
                        "jid": jid,
                        "공고": _label(prev),
                        "at": now,
                        "changes": {"active": {"before": True, "after": False}},
                    }
                )
        if ops:
            postings_col.bulk_write(ops, ordered=False)
        if changes:
            posting_changes_col.insert_many(changes)
        _merge_periods(fetched["periods"], now)
        _bump("ses", updatedAt=now)


# 지원자 수 이력은 바뀔 때만 한 점씩 쌓습니다. 접수 기간 동안 수십 번이면
# 충분하고, 문서가 끝없이 커지지 않게 오래된 점부터 버립니다.
_HISTORY_MAX = 200


def _push_applicants(history, row: dict, now: datetime) -> list:
    """[{"at", "count"}, ...] 에 이번 값을 더합니다 (직전과 같으면 그대로)."""
    history = list(history or [])
    count = row.get("참여인원")
    if count is None:
        return history
    if not history or history[-1]["count"] != count:
        history.append({"at": now, "count": count})
    return history[-_HISTORY_MAX:]


def _row_sig(row: dict) -> str:
    keys = (
        "기관명",
        "부서명",
        "근무지",
        "실습기간",
        "접수마감",
        "선발학과",
        "모집인원",
        "실습지원금",
    )
    return json.dumps([row.get(k) for k in keys], ensure_ascii=False)


def detail_is_stale(row: dict, max_age_seconds: int) -> bool:
    prev = load_snapshot()["postings"].get(row["jid"])
    if not prev or not prev.get("detail") or not prev.get("detailFetchedAt"):
        return True
    if prev.get("rowSig") != _row_sig(row):
        return True
    fetched = datetime.fromisoformat(prev["detailFetchedAt"])
    return (datetime.now(timezone.utc) - fetched).total_seconds() > max_age_seconds


# ── 마감 직전 점검 ──────────────────────────────────


def upcoming_deadlines() -> list[dict]:
    """아직 마감 직전 점검을 안 한 진행 중 공고: [{"jid", "deadlineAt", "label"}] (마감 이른 순).

    마감일이 바뀌면(연장) 새 마감일 기준으로 다시 점검합니다.
    """
    out = []
    cursor = postings_col.find(
        {"active": True, "deadlineAt": {"$gt": utcnow()}},
        {"기관명": 1, "부서명": 1, "deadlineAt": 1, "finalCheck": 1},
    ).sort("deadlineAt", 1)
    for d in cursor:
        if (d.get("finalCheck") or {}).get("deadlineAt") == d["deadlineAt"]:
            continue
        out.append({"jid": d["_id"], "deadlineAt": d["deadlineAt"], "label": _label(d)})
    return out


def mark_final_check(jids: list[str]) -> None:
    """마감 직전 점검 결과를 공고에 남깁니다 (마감 시점 지원자 수 아카이브)."""
    now = utcnow()
    ops = []
    for d in postings_col.find({"_id": {"$in": list(jids)}}):
        ops.append(
            UpdateOne(
                {"_id": d["_id"]},
                {
                    "$set": {
                        "finalCheck": {
                            "at": now,
                            "deadlineAt": d.get("deadlineAt"),
                            "참여인원": d.get("참여인원"),
                            "모집인원": d.get("모집인원"),
                        }
                    }
                },
            )
        )
    if ops:
        postings_col.bulk_write(ops, ordered=False)
        _bump("ses")


# ── 모집 기간 ───────────────────────────────────────


def _merge_periods(current: list[dict], now: datetime) -> None:
    """모집 기간 탭이 SES 에서 사라져도 지우지 않고 ended=True 로 남깁니다.
    그 기간 공고도 계속 보관하므로 웹에서 기간별로 골라 볼 수 있어야 합니다."""
    seen = set()
    for i, p in enumerate(current):
        seq = str(p["jsSeq"])
        seen.add(seq)
        periods_col.update_one(
            {"_id": seq},
            {
                "$set": {
                    "jsSeq": seq,
                    "name": p["name"],
                    "short": p.get("short", p["name"]),
                    "count": p.get("count"),
                    "order": i,
                    "ended": False,
                    "lastSeen": now,
                },
                "$setOnInsert": {"firstSeen": now},
                "$unset": {"endedAt": ""},
            },
            upsert=True,
        )
    periods_col.update_many(
        {"_id": {"$nin": list(seen)}, "ended": False},
        {"$set": {"ended": True, "endedAt": now}},
    )


def load_periods() -> list[dict]:
    """현재 탭(SES 순서) 다음에 내려간 기간(최근 것부터). 현재 탭이 앞에 와야
    기간별 색(탭 순서)이 그대로입니다."""
    docs = list(periods_col.find())
    current = sorted(
        (d for d in docs if not d.get("ended")), key=lambda d: d.get("order", 0)
    )
    ended = sorted(
        (d for d in docs if d.get("ended")),
        key=lambda d: d.get("lastSeen") or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return [
        {k: _iso(d.get(k)) for k in ("jsSeq", "name", "short", "count", "ended")}
        for d in current + ended
    ]


# ── 알림 판단을 끝낸 공고/글 ────────────────────────
# notified: {"_id": "ses:991", "kind": "ses", "key": "991", "제목": "...",
#            "reason": "notified" | "baseline" | "no-recipients" | "mail-disabled" | "migrated", "at"}


def seen_exists(kind: str = "ses") -> bool:
    """최초 실행 여부 - 기준선을 저장한 적이 있는지."""
    doc = meta_col.find_one({"_id": kind}, {"baselineAt": 1})
    return bool(doc and doc.get("baselineAt"))


def load_seen(kind: str = "ses") -> set[str]:
    return {d["key"] for d in notified_col.find({"kind": kind}, {"key": 1})}


def mark_seen(kind: str, items: list[tuple[str, str]], reason: str) -> None:
    """items: [(key, 사람이 읽을 이름)]. reason='baseline' 이면 최초 기준선으로 기록."""
    now = utcnow()
    ops = [
        UpdateOne(
            {"_id": f"{kind}:{key}"},
            {
                "$setOnInsert": {
                    "kind": kind,
                    "key": key,
                    "제목": label,
                    "reason": reason,
                    "at": now,
                }
            },
            upsert=True,
        )
        for key, label in items
    ]
    if ops:
        notified_col.bulk_write(ops, ordered=False)
    if reason == "baseline":
        meta_col.update_one({"_id": kind}, {"$set": {"baselineAt": now}}, upsert=True)


def posting_label(p: dict) -> str:
    return _label(p)


# ── 전자게시판 ──────────────────────────────────────

_board_cache = {"version": object(), "data": None}
_BOARD_ROW = (
    "artNo",
    "no",
    "category",
    "title",
    "writer",
    "date",
    "views",
    "hasFile",
    "hasImage",
)


def board_seen_exists() -> bool:
    return seen_exists("board")


def load_board_seen() -> set[str]:
    return load_seen("board")


def _art_id(art_no: str):
    return int(art_no) if str(art_no).isdigit() else str(art_no)


def load_board() -> dict:
    """웹 화면용 게시판 보관함: {"updatedAt", "total", "categories", "posts": {artNo: 글}}."""
    with _lock:
        version = _version("board")
        if _board_cache["version"] != version or _board_cache["data"] is None:
            meta = meta_col.find_one({"_id": "board"}) or {}
            posts = {}
            for d in board_posts_col.find().sort("_id", -1):
                p = _iso({k: v for k, v in d.items() if k != "_id"})
                posts[p["artNo"]] = p
            data = {
                "updatedAt": _iso(meta.get("updatedAt")),
                "total": meta.get("total"),
                "categories": meta.get("categories") or [],
                "posts": posts,
            }
            _board_cache.update(version=version, data=data)
        return _board_cache["data"]


def board_needs_detail(art_no: str) -> bool:
    post = load_board()["posts"].get(art_no)
    return not post or "contentHtml" not in post


def merge_board(fetched: dict, keep: int | None = None) -> None:
    """목록 값(제목·조회수 등)은 새로 읽은 것으로, 본문은 새로 받은 것만 바꿉니다.

    보관함이라 지난 글도 지우지 않습니다 (keep 은 예전 호환용, 쓰지 않음).
    """
    with _lock:
        now = utcnow()
        ops = []
        for row in fetched["listed"]:
            ops.append(
                UpdateOne(
                    {"_id": _art_id(row["artNo"])},
                    {
                        "$set": {k: row[k] for k in _BOARD_ROW if k in row}
                        | {"lastSeen": now},
                        "$setOnInsert": {"firstSeen": now},
                    },
                    upsert=True,
                )
            )
        for art_no, detail in fetched["details"].items():
            body = {k: v for k, v in detail.items() if k != "snippet"}
            # 목록의 '내용' 검색용 평문 (메일 미리보기와 같은 글자, 앞부분만)
            body["text"] = (detail.get("snippet") or "")[:600]
            body["detailFetchedAt"] = now
            ops.append(
                UpdateOne(
                    {"_id": _art_id(art_no)},
                    {
                        "$set": {**body, "artNo": str(art_no)},
                        "$setOnInsert": {"firstSeen": now},
                    },
                    upsert=True,
                )
            )
        if ops:
            board_posts_col.bulk_write(ops, ordered=True)
        # 제외 분류(교내채용)는 예전에 받아 둔 것도 지웁니다
        board_posts_col.delete_many({"category": {"$in": list(BOARD_EXCLUDE)}})
        old = meta_col.find_one({"_id": "board"}) or {}
        _bump(
            "board",
            updatedAt=now,
            total=fetched.get("total") or old.get("total"),
            categories=fetched.get("categories") or old.get("categories") or [],
        )


# ── 수신자 ──────────────────────────────────────────
# recipients: {"_id": 소문자 이메일, "email", "ses": bool, "board": bool,
#              "watch": [{"jid", "공고"}], "createdAt", "updatedAt"}
# 알림 종류별로 받을지 따로 켜고 끕니다. watch 는 지원자 수가 늘 때마다 알려 줄
# 관심 공고 목록 - 공고 이름을 같이 적어 두어 DB 만 봐도 무슨 공고인지 압니다.

KINDS = ("ses", "board")
_WATCH_MAX = 200


def _watch_list(value) -> list[str]:
    out = []
    for jid in value if isinstance(value, list) else []:
        if isinstance(jid, dict):
            jid = jid.get("jid")
        jid = str(jid or "").strip()
        if jid and jid not in out:
            out.append(jid)
    return out[:_WATCH_MAX]


def _watch_docs(jids: list[str], postings: dict | None = None) -> list[dict]:
    postings = load_snapshot()["postings"] if postings is None else postings
    return [
        {"jid": j, "공고": _label(postings[j]) if j in postings else ""} for j in jids
    ]


def _recipient_out(d: dict) -> dict:
    return {
        "email": d["email"],
        **{k: bool(d.get(k, True)) for k in KINDS},
        "watch": _watch_list(d.get("watch")),
    }


def load_recipients() -> list[dict]:
    return [_recipient_out(d) for d in recipients_col.find().sort("createdAt", 1)]


def recipients_for(kind: str) -> list[str]:
    """이 알림(ses/board)을 받기로 한 이메일들."""
    return [d["email"] for d in recipients_col.find({kind: True}).sort("createdAt", 1)]


def valid_email(email: str) -> bool:
    return bool(_EMAIL.match(email)) and len(email) <= 254


def add_recipient(email: str) -> list[dict]:
    email = email.strip()
    if not valid_email(email):
        raise ValueError("올바른 이메일 주소가 아닙니다.")
    now = utcnow()
    try:
        recipients_col.insert_one(
            {
                "_id": email.lower(),
                "email": email,
                **{k: True for k in KINDS},
                "watch": [],
                "createdAt": now,
                "updatedAt": now,
            }
        )
    except DuplicateKeyError:
        raise ValueError("이미 등록된 주소입니다.")
    return load_recipients()


def update_recipient(email: str, changes: dict) -> list[dict]:
    """알림 종류별 수신 여부·관심 공고를 바꿉니다. changes 예: {"board": False}, {"watch": [jid]}."""
    key = email.strip().lower()
    with _lock:
        if not recipients_col.find_one({"_id": key}, {"_id": 1}):
            raise KeyError("등록되지 않은 주소입니다.")
        update = {k: bool(changes[k]) for k in KINDS if changes.get(k) is not None}
        if changes.get("watch") is not None:
            jids = _watch_list(changes["watch"])
            update["watch"] = _watch_docs(jids)
            _baseline_watch_counts(jids)
        update["updatedAt"] = utcnow()
        recipients_col.update_one({"_id": key}, {"$set": update})
        return load_recipients()


def remove_recipient(email: str) -> list[dict]:
    recipients_col.delete_one({"_id": email.strip().lower()})
    return load_recipients()


# ── 관심 공고 지원자 수 ─────────────────────────────
# watches: {"_id": jid, "공고", "notifiedCount": 마지막으로 알린(또는 관심 등록 시점의)
#           지원자 수, "updatedAt"}. 지원자 수가 이 값보다 커지면 알림을 보내고 값을 올립니다.


def load_watch_counts() -> dict[str, int]:
    return {
        d["_id"]: d["notifiedCount"]
        for d in watches_col.find()
        if isinstance(d.get("notifiedCount"), int)
    }


def save_watch_counts(counts: dict[str, int]) -> None:
    with _lock:
        postings = load_snapshot()["postings"]
        old = load_watch_counts()
        now = utcnow()
        ops = [
            UpdateOne(
                {"_id": jid},
                {
                    "$set": {
                        "공고": _label(postings[jid]) if jid in postings else "",
                        "notifiedCount": n,
                        "updatedAt": now,
                    }
                },
                upsert=True,
            )
            for jid, n in counts.items()
            if old.get(jid) != n
        ]
        if ops:
            watches_col.bulk_write(ops, ordered=False)
        gone = [jid for jid in old if jid not in counts]
        if gone:
            watches_col.delete_many({"_id": {"$in": gone}})


def _baseline_watch_counts(jids: list[str]) -> None:
    """새로 관심 등록한 공고는 지금 지원자 수를 기준으로 삼습니다 -
    등록하자마자 기존 지원자만큼 알림이 가지 않게."""
    counts = load_watch_counts()
    postings = load_snapshot()["postings"]
    changed = False
    for jid in jids:
        count = (postings.get(jid) or {}).get("참여인원")
        if jid not in counts and isinstance(count, int):
            counts[jid] = count
            changed = True
    if changed:
        save_watch_counts(counts)


# ── 기록 (메일, 점검) ───────────────────────────────


def log_mail(
    kind: str, subject: str, to: list[str], ok: bool, error: str | None = None
) -> None:
    """보낸 메일 1통. kind: ses / board / watch / startup / test."""
    try:
        doc = {
            "at": utcnow(),
            "kind": kind,
            "subject": subject,
            "to": list(to),
            "ok": ok,
        }
        if error:
            doc["error"] = error
        mail_log_col.insert_one(doc)
    except Exception as e:  # 기록 실패로 발송 흐름이 깨지지 않게
        print(f"[!] 메일 기록 저장 실패: {e}")


def log_check(
    kind: str,
    reason: str,
    started: datetime,
    ok: bool,
    summary: dict | None = None,
    error: str | None = None,
) -> None:
    """점검 1회. kind: ses / board, reason: interval / deadline / manual."""
    finished = utcnow()
    try:
        doc = {
            "startedAt": started,
            "finishedAt": finished,
            "seconds": round((finished - started).total_seconds()),
            "kind": kind,
            "reason": reason,
            "ok": ok,
            "summary": summary or {},
        }
        if error:
            doc["error"] = error
        check_log_col.insert_one(doc)
    except Exception as e:
        print(f"[!] 점검 기록 저장 실패: {e}")


def recent_mails(limit: int = 20) -> list[dict]:
    return [
        _iso({k: v for k, v in d.items() if k != "_id"})
        for d in mail_log_col.find().sort("at", -1).limit(limit)
    ]


# ── 초기화 / 예전 JSON 옮기기 ───────────────────────


def init() -> None:
    """인덱스를 만들고, 예전 state/*.json 이 있으면 한 번만 DB 로 옮깁니다.
    옮긴 원본은 state/legacy-json/ 으로 치워 둡니다 (지워도 됩니다)."""
    ensure_indexes()
    if meta_col.find_one({"_id": "migration"}):
        return
    if not any(f.exists() for f in LEGACY_FILES.values()):
        meta_col.insert_one({"_id": "migration", "at": utcnow(), "from": None})
        return
    counts = _migrate_legacy()
    meta_col.insert_one(
        {"_id": "migration", "at": utcnow(), "from": "state/*.json", "counts": counts}
    )
    backup = STATE_DIR / "legacy-json"
    backup.mkdir(parents=True, exist_ok=True)
    for f in LEGACY_FILES.values():
        if f.exists():
            shutil.move(str(f), backup / f.name)
    print(f"[*] 예전 JSON 을 MongoDB 로 옮겼습니다: {counts} (원본은 {backup})")


def _read(name, default):
    try:
        with open(LEGACY_FILES[name], encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _migrate_legacy() -> dict:
    counts = {}
    now = utcnow()

    snap = _read("postings", {})
    postings = snap.get("postings") or {}
    ops = []
    for jid, p in postings.items():
        item = dict(p)
        item["jid"] = jid
        for k in ("firstSeen", "removedAt", "detailFetchedAt"):
            if item.get(k):
                item[k] = _dt(item[k])
        item["deadlineAt"] = _deadline_at(item.get("접수마감"))
        item["applicantsHistory"] = [
            {"at": _dt(t), "count": n} for t, n in item.get("applicantsHistory") or []
        ]
        item.setdefault("active", True)
        ops.append(ReplaceOne({"_id": jid}, _ordered(item), upsert=True))
    if ops:
        postings_col.bulk_write(ops)
    counts["postings"] = len(ops)
    updated = _dt(snap.get("updatedAt")) or now
    for i, p in enumerate(snap.get("periods") or []):
        periods_col.replace_one(
            {"_id": str(p["jsSeq"])},
            {
                "jsSeq": str(p["jsSeq"]),
                "name": p["name"],
                "short": p.get("short", p["name"]),
                "count": p.get("count"),
                "order": i,
                "ended": bool(p.get("ended")),
                "firstSeen": updated,
                "lastSeen": updated,
            },
            upsert=True,
        )
    if snap:
        _bump("ses", updatedAt=updated)

    seen = [k.removeprefix("jid:") for k in _read("seen", []) if isinstance(k, str)]
    mark_seen("ses", [(j, _label(postings.get(j, {}))) for j in seen], "migrated")
    if seen:
        meta_col.update_one(
            {"_id": "ses"}, {"$set": {"baselineAt": updated}}, upsert=True
        )
    counts["seen"] = len(seen)

    board = _read("board_posts", {})
    posts = board.get("posts") or {}
    if isinstance(posts, list):
        posts = {p["artNo"]: p for p in posts if isinstance(p, dict) and p.get("artNo")}
    ops = []
    for art_no, p in posts.items():
        item = {"artNo": str(art_no), **{k: v for k, v in p.items() if k != "artNo"}}
        for k in ("firstSeen", "detailFetchedAt"):
            if item.get(k):
                item[k] = _dt(item[k])
        ops.append(ReplaceOne({"_id": _art_id(art_no)}, item, upsert=True))
    if ops:
        board_posts_col.bulk_write(ops)
    counts["board_posts"] = len(ops)
    if board:
        _bump(
            "board",
            updatedAt=_dt(board.get("updatedAt")) or now,
            total=board.get("total"),
            categories=board.get("categories") or [],
        )
    bseen = [str(k) for k in _read("board_seen", [])]
    mark_seen(
        "board", [(a, (posts.get(a) or {}).get("title", "")) for a in bseen], "migrated"
    )
    if bseen:
        meta_col.update_one(
            {"_id": "board"}, {"$set": {"baselineAt": now}}, upsert=True
        )
    counts["board_seen"] = len(bseen)

    recips = _read("recipients", [])
    n = 0
    for i, e in enumerate(recips if isinstance(recips, list) else []):
        if isinstance(e, str):
            e = {"email": e}
        email = (e.get("email") or "").strip() if isinstance(e, dict) else ""
        if not email:
            continue
        recipients_col.replace_one(
            {"_id": email.lower()},
            {
                "email": email,
                **{k: bool(e.get(k, True)) for k in KINDS},
                "watch": _watch_docs(_watch_list(e.get("watch")), postings),
                # 원래 순서를 지키려고 1초씩 차이를 둡니다
                "createdAt": now + timedelta(seconds=i),
                "updatedAt": now,
            },
            upsert=True,
        )
        n += 1
    counts["recipients"] = n

    wc = _read("watch_counts", {})
    wc = wc if isinstance(wc, dict) else {}
    for jid, c in wc.items():
        if isinstance(c, int):
            watches_col.replace_one(
                {"_id": jid},
                {
                    "공고": _label(postings.get(jid, {})),
                    "notifiedCount": c,
                    "updatedAt": now,
                },
                upsert=True,
            )
    counts["watches"] = len(wc)
    return counts
