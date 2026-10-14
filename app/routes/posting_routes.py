from fastapi import APIRouter

from app.services import store, views

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
