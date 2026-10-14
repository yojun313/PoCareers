from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.core.security import is_admin
from app.core.templates import templates
from app.services import views

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
