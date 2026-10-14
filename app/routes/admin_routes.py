import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import GMAIL_ADDRESS
from app.core.security import require_admin
from app.services import notify, store
from app.services.scheduler import scheduler

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


class EmailBody(BaseModel):
    email: str


def _summary():
    snap = store.load_snapshot()
    active = [p for p in snap["postings"].values() if p.get("active", True)]
    return {
        "scheduler": scheduler.status(),
        "mailSender": GMAIL_ADDRESS,
        "recipients": store.load_recipients(),
        "updatedAt": snap["updatedAt"],
        "periods": snap["periods"],
        "activePostings": len(active),
        "companies": len({p.get("기관명") for p in active}),
    }


@router.get("/status")
async def status():
    return _summary()


@router.post("/recipients")
async def add_recipient(body: EmailBody):
    try:
        store.add_recipient(body.email)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"recipients": store.load_recipients()}


@router.delete("/recipients")
async def remove_recipient(body: EmailBody):
    return {"recipients": store.remove_recipient(body.email)}


@router.post("/recipients/test")
async def test_recipient(body: EmailBody):
    if not store.valid_email(body.email.strip()):
        raise HTTPException(status_code=400, detail="올바른 이메일 주소가 아닙니다.")
    try:
        # SMTP 는 블로킹이라 이벤트 루프를 막지 않도록 스레드에서 보냅니다.
        await asyncio.to_thread(notify.send_test, body.email.strip())
    except notify.MailNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"발송 실패: {e}")
    return {"ok": True}


@router.post("/check")
async def check_now():
    if not scheduler.trigger():
        raise HTTPException(
            status_code=409,
            detail="스케줄러가 실행 중이 아닙니다 (run.py --no-scheduler).",
        )
    return _summary()
