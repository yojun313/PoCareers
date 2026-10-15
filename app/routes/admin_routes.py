import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import GMAIL_ADDRESS
from app.core.security import require_admin
from app.services import board_views, notify, store, views
from app.services.scheduler import scheduler

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


class EmailBody(BaseModel):
    email: str


class RecipientPatch(BaseModel):
    email: str
    ses: bool | None = None
    board: bool | None = None
    watch: list[str] | None = None


def _watches(snap, recipients):
    """관심 공고 현황: 공고별 지원자 수와 관심 등록한 수신자."""
    counts = store.load_watch_counts()
    out = {}
    for r in recipients:
        for jid in r["watch"]:
            if jid not in out:
                p = snap["postings"].get(jid)
                view = views.posting_view(p) if p else {"jid": jid}
                out[jid] = {
                    "jid": jid,
                    "found": bool(p),
                    **{
                        k: view.get(k)
                        for k in (
                            "기관명",
                            "부서명",
                            "직무명",
                            "period",
                            "periodShort",
                            "jsSeq",
                            "companySlug",
                            "applicants",
                            "quota",
                            "ratio",
                            "applicantsDelta24h",
                            "applicantsChangedAt",
                            "closed",
                            "deadlineIso",
                        )
                    },
                    "notifiedCount": counts.get(jid),
                    "emails": [],
                }
            out[jid]["emails"].append(r["email"])
    return sorted(
        out.values(), key=lambda w: (bool(w["closed"]), w.get("기관명") or "")
    )


def _summary():
    snap = store.load_snapshot()
    active = [p for p in snap["postings"].values() if p.get("active", True)]
    recipients = store.load_recipients()
    return {
        "scheduler": scheduler.status(),
        "mailSender": GMAIL_ADDRESS,
        "recipients": recipients,
        "watches": _watches(snap, recipients),
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


@router.patch("/recipients")
async def update_recipient(body: RecipientPatch):
    try:
        recipients = store.update_recipient(
            body.email, {"ses": body.ses, "board": body.board, "watch": body.watch}
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=e.args[0])
    return {"recipients": recipients}


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


@router.get("/board")
async def board_list():
    """인턴 및 채용 공고 보관함 목록 (본문 제외). 학교 게시판 글이라 관리자만 봅니다."""
    return board_views.board_list()
