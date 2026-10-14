from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import APP_NAME, COOKIE_SECURE
from app.core.paths import STATIC_DIR
from app.core.security import is_admin
from app.core.templates import templates
from app.routes import admin_routes, auth_routes, page_routes, posting_routes

# API 문서(/docs 등)는 노출하지 않습니다 - Commeet 와 같은 이유.
app = FastAPI(title=APP_NAME, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def headers_middleware(request: Request, call_next):
    """API 응답 캐시 금지 + 보안 헤더 (Commeet app/main.py 와 같은 정책)."""
    response = await call_next(request)
    h = response.headers
    if request.url.path.startswith("/api/"):
        h["Cache-Control"] = "no-store"
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "font-src 'self' data:; connect-src 'self'; object-src 'none'; "
        "base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
    )
    if COOKIE_SECURE:
        h.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(page_routes.router)
app.include_router(auth_routes.router)
app.include_router(posting_routes.router)
app.include_router(admin_routes.router)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if request.url.path.startswith("/api") or exc.status_code != 404:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return templates.TemplateResponse(
        request=request,
        name="errors/404.html",
        context={"is_admin": is_admin(request)},
        status_code=404,
    )
