"""설정: .env 로드와 경로 상수.

.env 는 프로젝트 루트에서 읽습니다 - run.py 를 어느 폴더에서 실행하든
같은 파일을 쓰도록 작업 폴더(cwd)가 아니라 이 파일 위치를 기준으로 합니다.
.env 가 프로세스 환경변수보다 우선합니다 - pm2 는 다른 앱을 띄울 때 쓴
환경변수(PORT 등)를 물려줄 수 있어서, 환경변수를 우선하면 남의 포트를
잡으려다 죽었습니다. .env 에 없는 키만 환경변수에서 읽습니다.
"""

import hashlib
import os

from dotenv import load_dotenv

from app.core.paths import BASE_DIR

load_dotenv(BASE_DIR / ".env", override=True)


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


APP_NAME = "SES Notify"
APP_FULL_NAME = "POSTECH 현장실습 공고 알림"
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "yojun313@postech.ac.kr")

# ── SES ─────────────────────────────────────────────
SES_BASE = "https://ses.postech.ac.kr"
SES_SEARCH_URL = f"{SES_BASE}/student/manage/search/index.do"
SES_DETAIL_URL = f"{SES_BASE}/jobInternDetail.do"
SES_ID = os.getenv("SES_ID", "")
SES_PW = os.getenv("SES_PW", "")

# ── 메일 ────────────────────────────────────────────
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
MAIL_ENABLED = bool(GMAIL_ADDRESS and GMAIL_APP_PASSWORD)

# ── 스케줄러 ────────────────────────────────────────
# 최소 1분 - 그보다 짧으면 SES 서버에 부담만 줍니다.
CHECK_INTERVAL_SECONDS = max(60, int(_float("CHECK_INTERVAL_MINUTES", 10) * 60))
# 상세 페이지는 목록이 바뀌지 않아도 이 주기마다 한 번씩 다시 받습니다
# (모집 인원·일정 같은 상세만 바뀌는 경우 대비).
DETAIL_REFRESH_SECONDS = max(600, int(_float("DETAIL_REFRESH_HOURS", 6) * 3600))

# ── 웹 서버 ─────────────────────────────────────────
# 루프백 기본값은 Commeet 와 같은 이유입니다 - 프록시(nginx) 뒤에 둘 때
# 0.0.0.0 이면 프록시를 우회해 포트로 직접 접속됩니다.
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "7007"))
# 알림 메일의 "웹에서 보기" 링크에 씁니다. 비우면 링크를 넣지 않습니다.
BASE_URL = os.getenv("BASE_URL", "").strip().rstrip("/")
COOKIE_SECURE = BASE_URL.startswith("https://")

# ── 관리자 ──────────────────────────────────────────
ADMIN_ID = os.getenv("ADMIN_ID", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
ADMIN_ENABLED = bool(ADMIN_ID and ADMIN_PASSWORD)

SESSION_COOKIE_NAME = "ses_admin"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7일
# 비워 두면 관리자 계정에서 파생합니다 - 별도 설정 없이 재시작해도 로그인이
# 유지되고, 관리자 비밀번호를 바꾸면 기존 세션이 모두 무효가 됩니다.
SESSION_SECRET = (
    os.getenv("SESSION_SECRET", "").strip()
    or hashlib.sha256(
        f"ses-notify|{ADMIN_ID}|{ADMIN_PASSWORD}|{SES_PW}".encode()
    ).hexdigest()
)

# ── 상태 파일 ───────────────────────────────────────
STATE_DIR = BASE_DIR / "state"
STORAGE_FILE = STATE_DIR / "storage.json"  # SES 로그인 세션 쿠키
SEEN_FILE = STATE_DIR / "seen.json"  # 이미 알림 보낸 공고 키
POSTINGS_FILE = STATE_DIR / "postings.json"  # 웹에 보여 줄 공고 스냅샷
RECIPIENTS_FILE = (
    BASE_DIR / "recipients.json"
)  # 수신 이메일 목록 (관리자 화면에서 편집)
