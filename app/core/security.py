"""관리자 인증: .env 의 ADMIN_ID/ADMIN_PASSWORD 와 서명된 세션 쿠키.

세션은 서버에 저장하지 않습니다 - 쿠키에 서명된 타임스탬프 페이로드를
담아 (itsdangerous) 쿠키 자체가 "누가 보냈는지"의 근거가 됩니다.
"""

import secrets
import threading
import time

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import (
    ADMIN_ENABLED,
    ADMIN_ID,
    ADMIN_PASSWORD,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE,
    SESSION_SECRET,
)

_serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="ses-notify-admin")


def check_credentials(admin_id: str, password: str) -> bool:
    if not ADMIN_ENABLED:
        return False
    # 둘 다 비교한 뒤 합칩니다 - 아이디가 틀렸을 때 일찍 끝나면 응답 시간으로
    # 아이디 존재 여부가 드러납니다.
    id_ok = secrets.compare_digest(admin_id.encode(), ADMIN_ID.encode())
    pw_ok = secrets.compare_digest(password.encode(), ADMIN_PASSWORD.encode())
    return id_ok and pw_ok


def create_session_token() -> str:
    return _serializer.dumps({"admin": ADMIN_ID})


def is_admin(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token or not ADMIN_ENABLED:
        return False
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return False
    # .env 에서 관리자 아이디를 바꾸면 예전 쿠키는 통하지 않습니다.
    return data.get("admin") == ADMIN_ID


def require_admin(request: Request) -> None:
    if not is_admin(request):
        raise HTTPException(status_code=401, detail="관리자 로그인이 필요합니다.")


class LoginLimiter:
    """IP별 로그인 실패 횟수 제한 (메모리, 프로세스 하나 기준).

    관리자 계정이 하나뿐이라 비밀번호 대입을 막는 장치가 이것뿐입니다.
    """

    def __init__(self, max_failures: int = 5, window_seconds: int = 600):
        self.max_failures = max_failures
        self.window = window_seconds
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, ip: str, now: float) -> list[float]:
        stamps = [t for t in self._fails.get(ip, []) if now - t < self.window]
        self._fails[ip] = stamps
        return stamps

    def blocked(self, ip: str) -> bool:
        with self._lock:
            return len(self._recent(ip, time.time())) >= self.max_failures

    def fail(self, ip: str) -> None:
        with self._lock:
            now = time.time()
            self._recent(ip, now).append(now)

    def reset(self, ip: str) -> None:
        with self._lock:
            self._fails.pop(ip, None)


login_limiter = LoginLimiter()
