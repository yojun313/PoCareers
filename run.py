#!/usr/bin/env python3
"""
POSTECH SES 현장실습 기관 신규 공고 알림 - 단일 진입점.

실행:
  uv run run.py              # 1회 점검 후 신규 공고가 있으면 메일 발송
  uv run run.py --show       # 브라우저 창 띄워서 동작 확인(디버그)
  uv run run.py --dry-run    # 메일 발송 없이 신규 공고만 출력

리눅스 서버(Ubuntu)는 최초 1회:
  uv sync
  uv run playwright install --with-deps chromium
"""
import json
import os
import sys
import time
import traceback
from datetime import datetime

from config import load_env, require, write_private, SEEN, STATE_DIR
from ses_client import get_search_html
from parser import parse_postings
import notify


def load_seen(path=SEEN):
    if os.path.exists(path):
        try:
            return set(json.load(open(path, encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_seen(keys, path=SEEN):
    os.makedirs(STATE_DIR, exist_ok=True)
    write_private(path, json.dumps(sorted(keys), ensure_ascii=False, indent=2))


def check_once(env, show=False, dry=False):
    """1회 점검. 신규 공고가 있으면 발송하고 seen 갱신."""
    print("[*] 기업조회 페이지 로딩 중 ...")
    html = get_search_html(env["SES_ID"], env["SES_PW"], headless=not show)
    postings = parse_postings(html)
    print(f"[*] 현재 공고 {len(postings)}건 파싱.")

    first_run = not os.path.exists(SEEN)
    seen = load_seen()
    new = [p for p in postings if p["key"] not in seen]

    if first_run:
        print(f"[*] 최초 실행: 기존 {len(postings)}건을 기준선으로 저장(메일 미발송).")
        save_seen({p["key"] for p in postings})
        return 0

    if not new:
        print("[*] 신규 공고 없음.")
        return 0

    print(f"[+] 신규 공고 {len(new)}건:")
    for p in new:
        print(f"    - {p.get('기관명','')} / {p.get('부서명','')} "
              f"({p.get('실습기간','')}, 마감 {p.get('접수마감','')})")

    if dry:
        print("[*] --dry-run: 메일 미발송.")
        return 0

    recipients = notify.load_recipients()
    if not recipients:
        print("[!] 수신자가 없어 메일을 보내지 않습니다. seen 도 갱신하지 않습니다.")
        return 1

    require(env, "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD")
    if notify.send(env, new, recipients):
        # 발송 성공한 공고만 seen 에 추가 -> 한 번 보낸 건 재발송 안 함
        seen.update(p["key"] for p in new)
        save_seen(seen)
    return 0


def interval_seconds(env):
    try:
        minutes = float(env.get("CHECK_INTERVAL_MINUTES", "10"))
    except ValueError:
        minutes = 10.0
    return max(60, int(minutes * 60))  # 최소 60초


def main():
    show = "--show" in sys.argv
    dry = "--dry-run" in sys.argv
    once = "--once" in sys.argv

    env = load_env()
    require(env, "SES_ID", "SES_PW")

    if once:
        return check_once(env, show=show, dry=dry)

    period = interval_seconds(env)
    print(f"[*] 상주 모드 시작: {period // 60}분 주기로 점검합니다. (Ctrl+C 로 종료)")

    # 시작 알림 메일 1회 (발송 설정이 갖춰진 경우에만)
    if not dry:
        recipients = notify.load_recipients()
        if recipients and env.get("GMAIL_ADDRESS") and env.get("GMAIL_APP_PASSWORD"):
            try:
                notify.send_startup(env, recipients, period // 60)
            except Exception:
                print("[!] 시작 알림 메일 발송 실패 (점검은 계속 진행):")
                traceback.print_exc()

    while True:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n===== {stamp} 점검 =====")
        try:
            check_once(env, show=show, dry=dry)
        except KeyboardInterrupt:
            print("\n[*] 종료합니다.")
            return 0
        except Exception:
            # 일시적 오류(네트워크/세션 등)로 상주 프로세스가 죽지 않게 방어
            print("[!] 이번 점검 중 오류 발생 (다음 주기에 재시도):")
            traceback.print_exc()
        try:
            time.sleep(period)
        except KeyboardInterrupt:
            print("\n[*] 종료합니다.")
            return 0


if __name__ == "__main__":
    sys.exit(main())
