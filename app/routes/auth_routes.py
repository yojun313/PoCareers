from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.config import (
    ADMIN_ENABLED,
    COOKIE_SECURE,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE,
)
from app.core.security import check_credentials, create_session_token, login_limiter

router = APIRouter(prefix="/api/auth")


class LoginBody(BaseModel):
    id: str
    password: str


def _client_ip(request: Request) -> str:
    # nginx 뒤에서는 client.host 가 늘 127.0.0.1 이라 X-Real-IP 를 우선합니다.
    return request.headers.get("x-real-ip") or (
        request.client.host if request.client else ""
    )


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response):
    if not ADMIN_ENABLED:
        raise HTTPException(
            status_code=503,
            detail=".env 에 ADMIN_ID / ADMIN_PASSWORD 가 설정되지 않았습니다.",
        )
    ip = _client_ip(request)
    if login_limiter.blocked(ip):
        raise HTTPException(
            status_code=429,
            detail="로그인 시도가 너무 많습니다. 10분 뒤 다시 시도해 주세요.",
        )
    if not check_credentials(body.id.strip(), body.password):
        login_limiter.fail(ip)
        raise HTTPException(
            status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다."
        )
    login_limiter.reset(ip)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_token(),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
    )
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"ok": True}
