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
    CHECK_INTERVAL_SECONDS,
    DETAIL_REFRESH_SECONDS,
    MAIL_ENABLED,
    SES_ID,
    SES_PW,
)
from app.services import notify, store
from app.services.ses_client import fetch_all


def check_once(show: bool = False, dry: bool = False) -> dict:
    """1회 점검. 공고 스냅샷을 갱신하고, 신규 공고가 있으면 발송 후 seen 갱신.

    반환: {"total", "new", "sent"} 요약.
    """
    print("[*] SES 공고 수집 중 ...")
    fetched = fetch_all(
        SES_ID,
        SES_PW,
        need_detail=lambda r: store.detail_is_stale(r, DETAIL_REFRESH_SECONDS),
        headless=not show,
    )
    rows = fetched["rows"]
    for period in fetched["periods"]:
        print(f"    - {period['name']}: {period['count']}건")
    print(f"[*] 현재 공고 {len(rows)}건, 상세 {len(fetched['details'])}건 갱신.")
    store.merge_snapshot(fetched)

    summary = {"total": len(rows), "new": 0, "sent": False}
    first_run = not store.seen_exists()
    seen = store.migrate_seen(store.load_seen(), rows)

    if first_run:
        print(f"[*] 최초 실행: 기존 {len(rows)}건을 기준선으로 저장(메일 미발송).")
        store.save_seen({store.seen_key(r) for r in rows})
        return summary

    new = [r for r in rows if store.seen_key(r) not in seen]
    summary["new"] = len(new)
    if not new:
        store.save_seen(seen)  # 옛 키 -> 새 키 이전 결과 반영
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

    recipients = store.load_recipients()
    if not recipients:
        print("[!] 수신자가 없어 메일을 보내지 않습니다. seen 도 갱신하지 않습니다.")
        store.save_seen(seen)
        return summary
    if not MAIL_ENABLED:
        print("[!] .env 에 Gmail 발신 설정이 없어 메일을 보내지 않습니다.")
        store.save_seen(seen)
        return summary

    if notify.send_new_postings(new, recipients):
        # 발송 성공한 공고만 seen 에 추가 -> 한 번 보낸 건 재발송 안 함
        seen.update(store.seen_key(p) for p in new)
        summary["sent"] = True
    store.save_seen(seen)
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
        self.next_check_at = None
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
            "mailEnabled": MAIL_ENABLED,
            "dryRun": self._dry,
        }

    def _loop(self, startup_mail):
        print(f"[*] 스케줄러 시작: {self.interval // 60}분 주기로 점검합니다.")
        if startup_mail and not self._dry and MAIL_ENABLED:
            recipients = store.load_recipients()
            if recipients:
                try:
                    notify.send_startup(recipients, self.interval // 60)
                except Exception:
                    print("[!] 시작 알림 메일 발송 실패 (점검은 계속 진행):")
                    traceback.print_exc()

        while self.running:
            self._wake.clear()  # 점검 중에 눌린 "지금 점검"은 이번 점검으로 갈음
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n===== {stamp} 점검 =====")
            self.checking = True
            self.last_check_at = store.now_iso()
            try:
                self.last_summary = check_once(show=self._show, dry=self._dry)
                self.last_ok_at = self.last_check_at
                self.last_error = None
            except Exception as e:
                # 일시적 오류(네트워크/세션 등)로 상주 프로세스가 죽지 않게 방어
                print("[!] 이번 점검 중 오류 발생 (다음 주기에 재시도):")
                traceback.print_exc()
                self.last_error = f"{type(e).__name__}: {e}"
            finally:
                self.checking = False
            nxt = datetime.now(timezone.utc) + timedelta(seconds=self.interval)
            self.next_check_at = nxt.isoformat(timespec="seconds")
            self._wake.wait(self.interval)


scheduler = Scheduler()
