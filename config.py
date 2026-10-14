"""공통 설정/유틸: .env 로드, 경로 상수."""
import os
import sys

BASE = "https://ses.postech.ac.kr"
SEARCH_URL = f"{BASE}/student/manage/search/index.do"

STATE_DIR = "state"
STORAGE = os.path.join(STATE_DIR, "storage.json")   # 로그인 세션 쿠키
SEEN = os.path.join(STATE_DIR, "seen.json")         # 이미 알림 보낸 공고 키
RECIPIENTS = "recipients.json"                       # 수신 이메일 목록


def load_env(path=".env"):
    """.env 를 읽어 dict 로 반환. os.environ 값이 있으면 우선."""
    env = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    # 환경변수가 설정돼 있으면 그것으로 덮어쓰기 (CI/cron 대응)
    for k in ("SES_ID", "SES_PW", "SES_GROUP",
              "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "CHECK_INTERVAL_MINUTES"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def write_private(path, text):
    """민감 파일을 소유자만 읽기/쓰기(0600) 권한으로 저장."""
    import stat
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        pass


def require(env, *keys):
    missing = [k for k in keys if not env.get(k)]
    if missing:
        sys.exit(f"[!] .env 에 다음 항목이 필요합니다: {', '.join(missing)}")
