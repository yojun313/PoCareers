#!/usr/bin/env python3
"""
POSTECH SES 현장실습 공고 알림 + 공고 웹사이트 - 단일 진입점.

실행:
  uv run run.py                  # 메일 스케줄러 + 웹 서버 동시 실행 (기본)
  uv run run.py --once           # 1회 점검 후 종료 (cron 용, 웹 서버 없음)
  uv run run.py --dry-run        # 메일 발송 없이 동작 (스케줄러·웹 모두 실행)
  uv run run.py --no-web         # 스케줄러만
  uv run run.py --no-scheduler   # 웹 서버만 (저장된 공고만 보여 줌)
  uv run run.py --show           # 브라우저 창 띄워서 로그인 동작 확인(디버그)

리눅스 서버(Ubuntu)는 최초 1회:
  uv sync
  uv run playwright install --with-deps chromium
"""

import socket
import sys

from app.config import ADMIN_ENABLED, HOST, PORT, SES_ID, SES_PW


def port_in_use(host, port) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return True
    return False


def main():
    # nohup/systemd 처럼 터미널이 아닐 때도 로그가 바로바로 남도록.
    sys.stdout.reconfigure(line_buffering=True)
    args = set(sys.argv[1:])
    show = "--show" in args
    dry = "--dry-run" in args
    no_web = "--no-web" in args
    no_scheduler = "--no-scheduler" in args

    if not no_scheduler and not (SES_ID and SES_PW):
        sys.exit("[!] .env 에 SES_ID / SES_PW 가 필요합니다.")

    if "--once" in args:
        from app.services.scheduler import check_once

        check_once(show=show, dry=dry)
        return 0

    # 웹 포트를 스케줄러보다 먼저 확인합니다. 바인딩 실패로 죽으면 pm2 가
    # 계속 재시작하는데, 그때마다 스케줄러가 먼저 떠서 "시작 알림" 메일이
    # 재시작 횟수만큼 나갈 수 있습니다.
    if not no_web and port_in_use(HOST, PORT):
        sys.exit(
            f"[!] {HOST}:{PORT} 포트를 이미 다른 프로그램이 쓰고 있습니다. "
            ".env 의 PORT 를 바꾸세요."
        )

    from app.services.scheduler import scheduler

    if not no_scheduler:
        # 스케줄러는 별도 스레드 - Playwright sync API 는 uvicorn 의
        # asyncio 루프가 도는 스레드에서 쓸 수 없습니다.
        scheduler.start(show=show, dry=dry)

    if no_web:
        try:
            scheduler.join()
        except KeyboardInterrupt:
            print("\n[*] 종료합니다.")
        return 0

    import uvicorn
    from app.main import app

    if not ADMIN_ENABLED:
        print(
            "[!] .env 에 ADMIN_ID / ADMIN_PASSWORD 가 없어 관리자 화면에 로그인할 수 없습니다."
        )
    print(f"[*] 웹 서버: http://{HOST}:{PORT}")
    # Ctrl+C 는 uvicorn 이 받아 정상 종료하고, 스케줄러는 daemon 스레드라 함께 끝납니다.
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
    print("[*] 종료합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
