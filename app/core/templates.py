from fastapi.templating import Jinja2Templates

from app.config import (
    ADMIN_ENABLED,
    APP_FULL_NAME,
    APP_NAME,
    SES_SEARCH_URL,
    SUPPORT_EMAIL,
)
from app.core.paths import STATIC_DIR, TEMPLATES_DIR
from app.services import store


def asset(path: str) -> str:
    """정적 파일 URL 에 파일 수정 시각을 붙입니다.

    CSS/JS 를 고치면 URL 이 바뀌어 브라우저가 캐시된 옛 파일 대신 새 파일을
    받습니다 (StaticFiles 는 Cache-Control 을 보내지 않아 강력 새로고침 전까지
    옛 파일이 보일 수 있습니다).
    """
    file_path = STATIC_DIR / path.lstrip("/")
    try:
        version = int(file_path.stat().st_mtime)
    except OSError:
        version = 0
    return f"/static/{path.lstrip('/')}?v={version}"


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["APP_NAME"] = APP_NAME
templates.env.globals["APP_FULL_NAME"] = APP_FULL_NAME
templates.env.globals["SUPPORT_EMAIL"] = SUPPORT_EMAIL
templates.env.globals["SES_SEARCH_URL"] = SES_SEARCH_URL
templates.env.globals["ADMIN_ENABLED"] = ADMIN_ENABLED
templates.env.globals["asset"] = asset


def ses_periods() -> list[dict]:
    """현재 모집 기간 탭 (SES 탭 순서). 화면에서 기간별 색을 같은 순서로 맞추는 데 씁니다."""
    return [
        {"jsSeq": p["jsSeq"], "name": p["name"], "short": p.get("short", p["name"])}
        for p in store.load_snapshot()["periods"]
    ]


templates.env.globals["ses_periods"] = ses_periods
