from fastapi import APIRouter

from app.services import board_views, store, views
from app.services.scheduler import scheduler

router = APIRouter(prefix="/api")


@router.get("/postings")
async def list_postings():
    """공개 목록 - 상세 본문은 빼고 카드/필터에 필요한 값만."""
    snap = store.load_snapshot()
    return {
        "updatedAt": snap["updatedAt"],
        "periods": snap["periods"],
        "postings": views.all_postings(include_inactive=True),
    }


@router.get("/applicants")
async def list_applicants():
    """화면이 주기적으로 물어보는 가벼운 지원 현황 - 공고별 숫자만."""
    snap = store.load_snapshot()
    return {
        "updatedAt": snap["updatedAt"],
        "intervalMinutes": scheduler.interval // 60,
        "nextCheckAt": scheduler.next_check_at,
        "applicants": {jid: views.applicants(p) for jid, p in snap["postings"].items()},
    }


@router.get("/board")
async def list_board():
    """전자게시판 인턴 및 채용 공고 보관함 목록 (본문 제외)."""
    return board_views.board_list()
