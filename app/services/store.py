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

from app.config import POSTINGS_FILE, RECIPIENTS_FILE, SEEN_FILE, STATE_DIR

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


# ── 수신자 ──────────────────────────────────────────


def load_recipients() -> list[str]:
    data = _read_json(RECIPIENTS_FILE, [])
    if not isinstance(data, list):
        return []
    out, dup = [], set()
    for e in data:
        if isinstance(e, str) and e.strip() and e.strip().lower() not in dup:
            out.append(e.strip())
            dup.add(e.strip().lower())
    return out


def save_recipients(emails: list[str]) -> None:
    with _lock:
        _write_json(RECIPIENTS_FILE, emails, private=True)


def valid_email(email: str) -> bool:
    return bool(_EMAIL.match(email)) and len(email) <= 254


def add_recipient(email: str) -> list[str]:
    email = email.strip()
    if not valid_email(email):
        raise ValueError("올바른 이메일 주소가 아닙니다.")
    with _lock:
        current = load_recipients()
        if email.lower() in {e.lower() for e in current}:
            raise ValueError("이미 등록된 주소입니다.")
        current.append(email)
        save_recipients(current)
        return current


def remove_recipient(email: str) -> list[str]:
    with _lock:
        current = [e for e in load_recipients() if e.lower() != email.strip().lower()]
        save_recipients(current)
        return current
