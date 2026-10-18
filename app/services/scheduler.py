"""공고 점검 루프.

run.py 가 백그라운드 스레드로 띄우고, 웹 서버(관리자 화면)는 같은
프로세스에서 이 객체의 상태를 읽고 "지금 점검"을 요청합니다.
Playwright sync API 는 asyncio 이벤트 루프가 도는 스레드에서 쓸 수 없어서,
웹 서버(uvicorn) 스레드와 분리된 전용 스레드에서만 점검을 실행합니다.
"""

import threading
import traceback
from datetime import datetime, timedelta, timezone

from app.config import (
    BOARD_ENABLED,
    CHECK_INTERVAL_SECONDS,
    DETAIL_REFRESH_SECONDS,
    MAIL_ENABLED,
    STARTUP_MAIL,
    SES_ID,
    SES_PW,
)
from app.services import notify, store

# 마감 이 시간 전에 한 번 더 무조건 점검합니다 (마감 시점 지원자 수·상세 기록).
FINAL_CHECK_BEFORE = timedelta(minutes=1)
from app.services.board_client import fetch_board
from app.services.ses_client import fetch_all


def check_once(show: bool = False, dry: bool = False, force_detail=()) -> dict:
    """1회 점검. 공고 보관함을 갱신하고, 신규 공고가 있으면 발송 후 알림 기록.

    force_detail: 상세를 무조건 다시 받을 공고 jid (마감 직전 점검).
    반환: {"total", "new", "sent", "watch"} 요약.
    """
    print("[*] SES 공고 수집 중 ...")
    force = set(force_detail)
    fetched = fetch_all(
        SES_ID,
        SES_PW,
        need_detail=lambda r: (
            r["jid"] in force or store.detail_is_stale(r, DETAIL_REFRESH_SECONDS)
        ),
        headless=not show,
    )
    rows = fetched["rows"]
    for period in fetched["periods"]:
        print(f"    - {period['name']}: {period['count']}건")
    print(f"[*] 현재 공고 {len(rows)}건, 상세 {len(fetched['details'])}건 갱신.")
    store.merge_snapshot(fetched)

    summary = {"total": len(rows), "new": 0, "sent": False, "watch": 0}
    try:
        summary["watch"] = check_watches(dry=dry)
    except Exception:
        # 관심 공고 알림이 실패해도 신규 공고 알림은 그대로 진행합니다.
        print("[!] 관심 공고 지원자 알림 중 오류:")
        traceback.print_exc()

    def items(ps):
        return [(p["jid"], store.posting_label(p)) for p in ps]

    if not store.seen_exists("ses"):
        print(f"[*] 최초 실행: 기존 {len(rows)}건을 기준선으로 저장(메일 미발송).")
        store.mark_seen("ses", items(rows), "baseline")
        return summary

    seen = store.load_seen("ses")
    new = [r for r in rows if r["jid"] not in seen]
    summary["new"] = len(new)
    if not new:
        print("[*] 신규 공고 없음.")
        return summary

    print(f"[+] 신규 공고 {len(new)}건:")
    for p in new:
        print(
            f"    - [{p.get('periodShort', '')}] {p.get('기관명', '')} / {p.get('부서명', '')} "
            f"({p.get('실습기간', '')}, 마감 {p.get('접수마감', '')})"
        )

    if dry:
        print("[*] --dry-run: 메일 미발송.")
        return summary

    # 받을 사람이 없거나 메일 설정이 없으면 기록하지 않습니다 - 설정 후 다음 점검에 보냅니다.
    recipients = store.recipients_for("ses")
    if not recipients:
        print("[!] SES 알림 수신자가 없어 메일을 보내지 않습니다.")
        return summary
    if not MAIL_ENABLED:
        print("[!] .env 에 Gmail 발신 설정이 없어 메일을 보내지 않습니다.")
        return summary

    if notify.send_new_postings(new, recipients):
        # 발송 성공한 공고만 기록 -> 한 번 보낸 건 재발송 안 함
        store.mark_seen("ses", items(new), "notified")
        summary["sent"] = True
    return summary


def check_watches(dry: bool = False) -> int:
    """관심 공고의 지원자 수가 지난번 알린 값보다 늘었으면, 그 공고를 관심 등록한
    수신자에게 알립니다. 반환: 지원자가 늘어난 관심 공고 수."""
    recipients = [r for r in store.load_recipients() if r["watch"]]
    if not recipients:
        return 0
    postings = store.load_snapshot()["postings"]
    counts = store.load_watch_counts()
    watched = {jid for r in recipients for jid in r["watch"]}
    nxt = {jid: n for jid, n in counts.items() if jid in watched}
    changes = {}  # jid -> (이전, 지금)
    for jid in watched:
        p = postings.get(jid)
        count = p.get("참여인원") if p and p.get("active", True) else None
        if not isinstance(count, int):
            continue
        before = counts.get(jid)
        if before is not None and count > before:
            changes[jid] = (before, count)
        # 줄어든 경우(지원 취소)도 기준을 낮춰 둡니다 - 다시 늘면 그때 알림
        nxt[jid] = count
    if not changes:
        store.save_watch_counts(nxt)
        return 0

    for jid, (before, count) in changes.items():
        p = postings[jid]
        print(
            f"[+] 관심 공고 지원자 증가: {p.get('기관명', '')} / {p.get('부서명', '')} {before} -> {count}명"
        )
    if dry:
        print("[*] --dry-run: 관심 공고 알림 미발송.")
        return len(changes)
    if not MAIL_ENABLED:
        print("[!] .env 에 Gmail 발신 설정이 없어 관심 공고 알림을 보내지 않습니다.")
        store.save_watch_counts(nxt)
        return len(changes)

    for r in recipients:
        mine = [(postings[jid], *changes[jid]) for jid in r["watch"] if jid in changes]
        if not mine:
            continue
        try:
            notify.send_applicant_alert(mine, r["email"])
        except Exception:
            # 실패한 공고는 기준을 올리지 않아 다음 점검에 다시 보냅니다
            print(f"[!] {r['email']} 관심 공고 알림 발송 실패:")
            traceback.print_exc()
            for p, before, _ in mine:
                nxt[p["jid"]] = before
    store.save_watch_counts(nxt)
    return len(changes)


def _board_items(posts):
    return [(p["artNo"], p.get("title", "")) for p in posts]


def check_board(show: bool = False, dry: bool = False) -> dict:
    """전자게시판 '인턴 및 채용 공고' 1회 점검. 새 글이 있으면 board 수신자에게 발송.

    웹 화면용 보관함(최근 글 + 본문)도 이때 함께 채웁니다.
    반환: {"new", "sent"} 요약.
    """
    print("[*] 전자게시판 인턴 및 채용 공고 확인 중 ...")
    first_run = not store.board_seen_exists()
    seen = None if first_run else store.load_board_seen()
    fetched = fetch_board(
        SES_ID,
        SES_PW,
        seen,
        have={k: p.get("category", "") for k, p in store.load_board()["posts"].items()},
        need_detail=store.board_needs_detail,
        headless=not show,
    )
    store.merge_board(fetched)
    print(
        f"[*] 게시판 목록 {len(fetched['listed'])}건, 본문 {len(fetched['details'])}건 갱신."
    )

    if first_run:
        print(
            f"[*] 게시판 최초 실행: 지금 있는 글 {len(fetched['listed'])}건을 기준선으로 저장(메일 미발송)."
        )
        store.mark_seen("board", _board_items(fetched["listed"]), "baseline")
        return {"new": 0, "sent": False}

    new = fetched["new"]
    summary = {"new": len(new), "sent": False}
    if not new:
        print("[*] 게시판 새 글 없음.")
        return summary

    print(f"[+] 게시판 새 글 {len(new)}건:")
    for p in new:
        print(
            f"    - [{p.get('category', '')}] {p.get('title', '')} ({p.get('writer', '')})"
        )
    if dry:
        print("[*] --dry-run: 메일 미발송.")
        return summary

    recipients = store.recipients_for("board")
    if not recipients:
        # 받을 사람이 없으면 본 것으로 칩니다 - 나중에 누가 켜도 지난 글이 몰려오지 않게
        print("[*] 게시판 알림 수신자가 없어 메일을 보내지 않습니다.")
        store.mark_seen("board", _board_items(new), "no-recipients")
        return summary
    if not MAIL_ENABLED:
        print("[!] .env 에 Gmail 발신 설정이 없어 메일을 보내지 않습니다.")
        store.mark_seen("board", _board_items(new), "mail-disabled")
        return summary

    if notify.send_board_posts(new, recipients):
        summary["sent"] = True
        store.mark_seen("board", _board_items(new), "notified")
    return summary


class Scheduler:
    def __init__(self):
        self.interval = CHECK_INTERVAL_SECONDS
        self.running = False
        self.checking = False
        self.last_check_at = None
        self.last_ok_at = None
        self.last_error = None
        self.last_summary = None
        self.board_enabled = BOARD_ENABLED
        self.board_last_ok_at = None
        self.board_last_error = None
        self.board_last_summary = None
        self.next_check_at = None
        self.next_deadline_check = None
        self._manual = False
        self._wake = threading.Event()
        self._thread = None
        self._show = False
        self._dry = False

    def start(self, show=False, dry=False, startup_mail=True):
        self._show, self._dry = show, dry
        self.running = True
        self._thread = threading.Thread(
            target=self._loop, args=(startup_mail,), name="ses-scheduler", daemon=True
        )
        self._thread.start()

    def join(self):
        if self._thread:
            self._thread.join()

    def trigger(self) -> bool:
        """다음 주기를 기다리지 않고 바로 점검하게 합니다."""
        if not self.running:
            return False
        self._manual = True
        self._wake.set()
        return True

    def status(self) -> dict:
        return {
            "running": self.running,
            "checking": self.checking,
            "intervalMinutes": self.interval // 60,
            "lastCheckAt": self.last_check_at,
            "lastOkAt": self.last_ok_at,
            "lastError": self.last_error,
            "lastSummary": self.last_summary,
            "nextCheckAt": self.next_check_at,
            "nextDeadlineCheck": self.next_deadline_check,
            "mailEnabled": MAIL_ENABLED,
            "dryRun": self._dry,
            "board": {
                "enabled": self.board_enabled,
                "lastOkAt": self.board_last_ok_at,
                "lastError": self.board_last_error,
                "lastSummary": self.board_last_summary,
            },
        }

    def _loop(self, startup_mail):
        print(
            f"[*] 스케줄러 시작: {self.interval // 60}분 주기로 점검합니다 (+ 공고 마감 1분 전)."
        )
        if startup_mail and STARTUP_MAIL and not self._dry and MAIL_ENABLED:
            recipients = [
                r["email"]
                for r in store.load_recipients()
                if any(r.get(k) for k in store.KINDS)
            ]
            if recipients:
                try:
                    notify.send_startup(recipients, self.interval // 60)
                except Exception:
                    print("[!] 시작 알림 메일 발송 실패 (점검은 계속 진행):")
                    traceback.print_exc()

        next_regular = store.utcnow()
        while self.running:
            self._wake.clear()  # 점검 중에 눌린 "지금 점검"은 이번 점검으로 갈음
            now = store.utcnow()
            manual, self._manual = self._manual, False
            # 마감 1분 전이 된 공고 - 주기와 상관없이 이번에 무조건 다시 받습니다.
            due = [
                u
                for u in self._upcoming()
                if u["deadlineAt"] - FINAL_CHECK_BEFORE <= now + timedelta(seconds=2)
            ]
            regular = manual or now >= next_regular
            if regular or due:
                reason = "manual" if manual else ("interval" if regular else "deadline")
                stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                label = {
                    "manual": "수동 점검",
                    "interval": "점검",
                    "deadline": "마감 직전 점검",
                }[reason]
                print(f"\n===== {stamp} {label} =====")
                if due:
                    print(f"[*] 곧 마감: {', '.join(u['label'] for u in due)}")
                self._run(reason, [u["jid"] for u in due], board=regular)
                if regular:
                    next_regular = store.utcnow() + timedelta(seconds=self.interval)

            upcoming = self._upcoming()
            target = next_regular
            self.next_deadline_check = None
            if upcoming:
                first = upcoming[0]
                at = first["deadlineAt"] - FINAL_CHECK_BEFORE
                same = [u for u in upcoming if u["deadlineAt"] == first["deadlineAt"]]
                self.next_deadline_check = {
                    "at": store._iso(at),
                    "deadlineAt": store._iso(first["deadlineAt"]),
                    "label": first["label"],
                    "count": len(same),
                }
                target = min(target, at)
            self.next_check_at = store._iso(next_regular)
            self._wake.wait(max(1.0, (target - store.utcnow()).total_seconds()))

    def _upcoming(self) -> list[dict]:
        try:
            return store.upcoming_deadlines()
        except Exception:
            traceback.print_exc()
            return []

    def _run(self, reason: str, due: list[str], board: bool):
        self.checking = True
        self.last_check_at = store.now_iso()
        started = store.utcnow()
        try:
            self.last_summary = check_once(
                show=self._show, dry=self._dry, force_detail=due
            )
            self.last_summary["reason"] = reason
            self.last_ok_at = self.last_check_at
            self.last_error = None
            if due:
                store.mark_final_check(due)
            store.log_check(
                "ses", reason, started, True, {**self.last_summary, "deadlineJids": due}
            )
        except Exception as e:
            # 일시적 오류(네트워크/세션 등)로 상주 프로세스가 죽지 않게 방어
            print("[!] 이번 점검 중 오류 발생 (다음 주기에 재시도):")
            traceback.print_exc()
            self.last_error = f"{type(e).__name__}: {e}"
            store.log_check(
                "ses", reason, started, False, {"deadlineJids": due}, self.last_error
            )
        if board and self.board_enabled:
            # 게시판은 SES 와 별개 - 한쪽이 실패해도 다른 쪽은 진행합니다.
            started = store.utcnow()
            try:
                self.board_last_summary = check_board(show=self._show, dry=self._dry)
                self.board_last_ok_at = store.now_iso()
                self.board_last_error = None
                store.log_check("board", reason, started, True, self.board_last_summary)
            except Exception as e:
                print("[!] 게시판 점검 중 오류 발생 (다음 주기에 재시도):")
                traceback.print_exc()
                self.board_last_error = f"{type(e).__name__}: {e}"
                store.log_check(
                    "board", reason, started, False, None, self.board_last_error
                )
        self.checking = False


scheduler = Scheduler()
