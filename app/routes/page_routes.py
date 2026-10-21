from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.core.security import is_admin
from app.core.templates import templates
from app.config import BOARD_NAME, board_list_page_url
from app.services import board_views, views

router = APIRouter()


@router.get("/")
async def home(request: Request):
    return templates.TemplateResponse(
        request=request, name="home.html", context={"is_admin": is_admin(request)}
    )


@router.get("/calendar")
async def calendar_page(request: Request):
    return templates.TemplateResponse(
        request=request, name="calendar.html", context={"is_admin": is_admin(request)}
    )


@router.get("/company/{slug}")
async def company_page(request: Request, slug: str):
    data = views.company(slug)
    if data is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="company.html",
        context={"is_admin": is_admin(request), "company": data},
    )


@router.get("/sign-in")
async def sign_in_page(request: Request):
    if is_admin(request):
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(
        request=request, name="auth/sign_in.html", context={"is_admin": False}
    )


@router.get("/admin")
async def admin_page(request: Request):
    if not is_admin(request):
        return RedirectResponse("/sign-in", status_code=303)
    return templates.TemplateResponse(
        request=request, name="admin.html", context={"is_admin": True}
    )


# 전자게시판 인턴 및 채용 공고 - 로그인 없이 누구나 봅니다.
@router.get("/board")
async def board_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="board.html",
        context={
            "is_admin": is_admin(request),
            "board_name": BOARD_NAME,
            "board_url": board_list_page_url(),
        },
    )


@router.get("/board/{art_no}")
async def board_post_page(request: Request, art_no: str):
    post = board_views.board_post(art_no) if art_no.isdigit() else None
    if post is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="board_post.html",
        context={
            "is_admin": is_admin(request),
            "post": post,
            "board_name": BOARD_NAME,
            "board_url": board_list_page_url(),
        },
    )
