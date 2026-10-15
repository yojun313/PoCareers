"""상태 파일 읽기/쓰기: 공고 스냅샷, 알림 보낸 공고, 수신자 목록.

스케줄러 스레드가 쓰고 웹 서버가 읽습니다. 쓰기는 임시 파일에 쓴 뒤
os.replace 로 바꿔치기해서, 읽는 쪽이 반쯤 쓰인 파일을 보는 일이 없습니다.
"""

import json
import os
import re
import stat
import threading
from datetime import datetime, timezone

from app.config import (
    BOARD_EXCLUDE,
    BOARD_POSTS_FILE,
    BOARD_SEEN_FILE,
    POSTINGS_FILE,
    RECIPIENTS_FILE,
    SEEN_FILE,
    STATE_DIR,
    WATCH_COUNTS_FILE,
)

_lock = threading.RLock()
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path, data, private=False):
    os.makedirs(path.parent, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if private:
        try:
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError:
            pass
    os.replace(tmp, path)


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


# ── 공고 스냅샷 ─────────────────────────────────────

_snapshot_cache = {"mtime": None, "data": None}


def load_snapshot() -> dict:
    """{"updatedAt", "periods", "postings": {jid: posting}}. 파일이 바뀔 때만 다시 읽습니다."""
    with _lock:
        try:
            mtime = POSTINGS_FILE.stat().st_mtime
        except OSError:
            return {"updatedAt": None, "periods": [], "postings": {}}
        if _snapshot_cache["mtime"] != mtime:
            data = _read_json(POSTINGS_FILE, {})
            data.setdefault("updatedAt", None)
            data.setdefault("periods", [])
            data.setdefault("postings", {})
            _snapshot_cache.update(mtime=mtime, data=data)
        return _snapshot_cache["data"]


def merge_snapshot(fetched: dict) -> dict:
    """새로 받은 목록을 스냅샷에 합칩니다.

    - 목록에 있는 공고: 목록 값 갱신, 상세는 새로 받은 게 있을 때만 교체
    - 목록에서 사라진 공고: 지우지 않고 active=False (웹에서 "마감" 으로 표시)
    """
    with _lock:
        old = load_snapshot()
        postings = {jid: dict(p) for jid, p in old["postings"].items()}
        stamp = now_iso()
        current = set()
        for row in fetched["rows"]:
            jid = row["jid"]
            current.add(jid)
            prev = postings.get(jid, {})
            item = {k: v for k, v in row.items() if k != "legacyKey"}
            item["firstSeen"] = prev.get("firstSeen", stamp)
            item["applicantsHistory"] = _push_applicants(
                prev.get("applicantsHistory"), row, stamp
            )
            item["active"] = True
            item.pop("removedAt", None)
            if jid in fetched["details"]:
                item["detail"] = fetched["details"][jid]
                item["detailFetchedAt"] = stamp
            else:
                item["detail"] = prev.get("detail")
                item["detailFetchedAt"] = prev.get("detailFetchedAt")
            # 목록 값이 바뀌면 다음 점검 때 상세도 다시 받도록 지문을 남깁니다.
            item["rowSig"] = _row_sig(row)
            postings[jid] = item
        for jid, p in postings.items():
            if jid not in current and p.get("active", True):
                p["active"] = False
                p["removedAt"] = stamp
        data = {"updatedAt": stamp, "periods": fetched["periods"], "postings": postings}
        _write_json(POSTINGS_FILE, data)
        return data


# 지원자 수 이력은 바뀔 때만 한 점씩 쌓습니다. 접수 기간 동안 수십 번이면
# 충분하고, 파일이 끝없이 커지지 않게 오래된 점부터 버립니다.
_HISTORY_MAX = 200


def _push_applicants(history, row: dict, stamp: str) -> list:
    """[[시각, 지원자 수], ...] 에 이번 값을 더합니다 (직전과 같으면 그대로)."""
    history = list(history or [])
    count = row.get("참여인원")
    if count is None:
        return history
    if not history or history[-1][1] != count:
        history.append([stamp, count])
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


# ── 알림 보낸 공고 ──────────────────────────────────


def seen_exists() -> bool:
    return SEEN_FILE.exists()


def load_seen() -> set[str]:
    data = _read_json(SEEN_FILE, [])
    return set(data) if isinstance(data, list) else set()


def save_seen(keys: set[str]) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    _write_json(SEEN_FILE, sorted(keys), private=True)


def seen_key(row: dict) -> str:
    """공고 고유 키. SES 의 공고 번호(jidSeq)라 마감일 등이 바뀌어도 같습니다."""
    return f"jid:{row['jid']}"


def migrate_seen(seen: set[str], rows: list[dict]) -> set[str]:
    """예전 키(목록 값 해시)를 새 키로 옮깁니다.

    예전 알림기가 이미 보낸 공고를 "신규"로 다시 보내지 않기 위함입니다.
    예전 키와 짝이 맞지 않는 공고는 실제로 알림을 받은 적이 없는 것이므로
    (예전에는 기본 탭 하나만 봤습니다) 신규로 남겨 둡니다.
    """
    legacy = {k for k in seen if not k.startswith("jid:")}
    if not legacy:
        return seen
    migrated = {k for k in seen if k.startswith("jid:")}
    for row in rows:
        if row.get("legacyKey") in legacy:
            migrated.add(seen_key(row))
    return migrated


# ── 전자게시판 ──────────────────────────────────────


def board_seen_exists() -> bool:
    return BOARD_SEEN_FILE.exists()


def load_board_seen() -> set[str]:
    data = _read_json(BOARD_SEEN_FILE, [])
    return set(data) if isinstance(data, list) else set()


# 게시판은 계속 쌓이므로 최근 것만 기억합니다. 한 번 점검에 보는 글은 많아야
# 50건이라, 이보다 오래된 글이 다시 "새 글"로 잡힐 일은 없습니다.
_BOARD_SEEN_MAX = 1000


def save_board_seen(keys: set[str]) -> None:
    newest = sorted(keys, key=lambda k: int(k) if k.isdigit() else 0)[-_BOARD_SEEN_MAX:]
    _write_json(BOARD_SEEN_FILE, newest)


_board_cache = {"mtime": None, "data": None}


def load_board() -> dict:
    """웹 화면용 게시판 보관함: {"updatedAt", "total", "categories", "posts": {artNo: 글}}."""
    with _lock:
        try:
            mtime = BOARD_POSTS_FILE.stat().st_mtime
        except OSError:
            return {"updatedAt": None, "total": None, "categories": [], "posts": {}}
        if _board_cache["mtime"] != mtime:
            data = _read_json(BOARD_POSTS_FILE, {})
            posts = data.get("posts") or {}
            if isinstance(posts, list):  # 예전 형식(최근 글 목록)
                posts = {
                    p["artNo"]: p
                    for p in posts
                    if isinstance(p, dict) and p.get("artNo")
                }
            data = {
                "updatedAt": data.get("updatedAt"),
                "total": data.get("total"),
                "categories": data.get("categories") or [],
                "posts": posts,
            }
            _board_cache.update(mtime=mtime, data=data)
        return _board_cache["data"]


def board_needs_detail(art_no: str) -> bool:
    post = load_board()["posts"].get(art_no)
    return not post or "contentHtml" not in post


def merge_board(fetched: dict, keep: int) -> None:
    """목록 값(제목·조회수 등)은 새로 읽은 것으로, 본문은 새로 받은 것만 바꿉니다.
    글 번호가 큰(최근) 것부터 keep 건만 남깁니다."""
    with _lock:
        old = load_board()
        posts = {k: dict(v) for k, v in old["posts"].items()}
        stamp = now_iso()
        for row in fetched["listed"]:
            item = posts.get(row["artNo"], {})
            item.update(
                {
                    k: v
                    for k, v in row.items()
                    if k not in ("contentHtml", "snippet", "attachments")
                }
            )
            item.setdefault("firstSeen", stamp)
            posts[row["artNo"]] = item
        for art_no, detail in fetched["details"].items():
            item = posts.setdefault(art_no, {"artNo": art_no, "firstSeen": stamp})
            item.update(detail)
            # 목록의 '내용' 검색용 평문 (메일 미리보기와 같은 글자, 길이 제한 없이 앞부분만)
            item["text"] = (detail.get("snippet") or "")[:600]
            item.pop("snippet", None)
            item["detailFetchedAt"] = stamp
        # 제외 분류(교내채용)는 예전에 받아 둔 것도 지웁니다
        posts = {
            k: v for k, v in posts.items() if v.get("category") not in BOARD_EXCLUDE
        }
        newest = sorted(
            posts, key=lambda k: int(k) if k.isdigit() else 0, reverse=True
        )[:keep]
        _write_json(
            BOARD_POSTS_FILE,
            {
                "updatedAt": stamp,
                "total": fetched.get("total") or old["total"],
                "categories": fetched.get("categories") or old["categories"],
                "posts": {k: posts[k] for k in newest},
            },
        )


# ── 수신자 ──────────────────────────────────────────
# recipients.json: [{"email": "...", "ses": true, "board": true, "watch": [jid, ...]}, ...]
# 알림 종류별로 받을지 따로 켜고 끕니다. 예전 형식(이메일 문자열 목록)은
# 읽을 때 "둘 다 받음"으로 바꿔 읽습니다. watch 는 지원자 수가 늘 때마다
# 알려 줄 관심 공고(jid) 목록입니다.

KINDS = ("ses", "board")
_WATCH_MAX = 200


def _watch_list(value) -> list[str]:
    out = []
    for jid in value if isinstance(value, list) else []:
        jid = str(jid).strip()
        if jid and jid not in out:
            out.append(jid)
    return out[:_WATCH_MAX]


def _normalize(entry) -> dict | None:
    if isinstance(entry, str):
        entry = {"email": entry}
    if not isinstance(entry, dict) or not isinstance(entry.get("email"), str):
        return None
    email = entry["email"].strip()
    if not email:
        return None
    return {
        "email": email,
        **{k: bool(entry.get(k, True)) for k in KINDS},
        "watch": _watch_list(entry.get("watch")),
    }


def load_recipients() -> list[dict]:
    data = _read_json(RECIPIENTS_FILE, [])
    if not isinstance(data, list):
        return []
    out, dup = [], set()
    for e in data:
        r = _normalize(e)
        if r and r["email"].lower() not in dup:
            out.append(r)
            dup.add(r["email"].lower())
    return out


def recipients_for(kind: str) -> list[str]:
    """이 알림(ses/board)을 받기로 한 이메일들."""
    return [r["email"] for r in load_recipients() if r.get(kind)]


def save_recipients(recipients: list[dict]) -> None:
    with _lock:
        _write_json(RECIPIENTS_FILE, recipients, private=True)


def valid_email(email: str) -> bool:
    return bool(_EMAIL.match(email)) and len(email) <= 254


def add_recipient(email: str) -> list[dict]:
    email = email.strip()
    if not valid_email(email):
        raise ValueError("올바른 이메일 주소가 아닙니다.")
    with _lock:
        current = load_recipients()
        if email.lower() in {r["email"].lower() for r in current}:
            raise ValueError("이미 등록된 주소입니다.")
        current.append({"email": email, **{k: True for k in KINDS}, "watch": []})
        save_recipients(current)
        return current


def update_recipient(email: str, changes: dict) -> list[dict]:
    """알림 종류별 수신 여부·관심 공고를 바꿉니다. changes 예: {"board": False}, {"watch": [jid]}."""
    with _lock:
        current = load_recipients()
        target = next(
            (r for r in current if r["email"].lower() == email.strip().lower()), None
        )
        if target is None:
            raise KeyError("등록되지 않은 주소입니다.")
        for k in KINDS:
            if k in changes and changes[k] is not None:
                target[k] = bool(changes[k])
        if changes.get("watch") is not None:
            target["watch"] = _watch_list(changes["watch"])
            _baseline_watch_counts(target["watch"])
        save_recipients(current)
        return current


def remove_recipient(email: str) -> list[dict]:
    with _lock:
        current = [
            r for r in load_recipients() if r["email"].lower() != email.strip().lower()
        ]
        save_recipients(current)
        return current


# ── 관심 공고 지원자 수 ─────────────────────────────
# watch_counts.json: {jid: 마지막으로 알린(또는 관심 등록 시점의) 지원자 수}
# 지원자 수가 이 값보다 커지면 알림을 보내고 값을 올립니다.


def load_watch_counts() -> dict[str, int]:
    data = _read_json(WATCH_COUNTS_FILE, {})
    return (
        {k: v for k, v in data.items() if isinstance(v, int)}
        if isinstance(data, dict)
        else {}
    )


def save_watch_counts(counts: dict[str, int]) -> None:
    with _lock:
        _write_json(WATCH_COUNTS_FILE, counts)


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
