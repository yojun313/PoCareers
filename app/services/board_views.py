"""게시판 보관함 -> 화면용 데이터."""

from datetime import datetime, timedelta

from app.config import board_post_url
from app.services import store
from app.services.views import KST

NEW_DAYS = 3  # 등록일이 이 기간 안이면 N 표시 (게시판과 같은 방식)


def _sorted_posts() -> list[dict]:
    posts = store.load_board()["posts"].values()
    return sorted(
        posts,
        key=lambda p: int(p["artNo"]) if p["artNo"].isdigit() else 0,
        reverse=True,
    )


def _is_new(date: str) -> bool:
    try:
        d = datetime.strptime(date, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return False
    return datetime.now(KST).date() - d < timedelta(days=NEW_DAYS)


def post_row(p: dict) -> dict:
    return {
        "artNo": p["artNo"],
        "no": p.get("no", ""),
        "category": p.get("category", ""),
        "title": p.get("title", ""),
        "writer": p.get("writer", ""),
        "date": p.get("date", ""),
        "views": p.get("views"),
        "hasFile": p.get("hasFile", False),
        "hasImage": p.get("hasImage", False),
        "isNew": _is_new(p.get("date", "")),
        # 목록 검색용 (제목·작성자 외 '내용' 검색)
        "text": p.get("text", ""),
    }


def board_list() -> dict:
    data = store.load_board()
    return {
        "updatedAt": data["updatedAt"],
        "total": data["total"],
        "categories": data["categories"],
        "posts": [post_row(p) for p in _sorted_posts()],
    }


def board_post(art_no: str) -> dict | None:
    posts = _sorted_posts()
    idx = next((i for i, p in enumerate(posts) if p["artNo"] == art_no), None)
    if idx is None:
        return None
    p = posts[idx]
    newer = posts[idx - 1] if idx > 0 else None
    older = posts[idx + 1] if idx + 1 < len(posts) else None
    return {
        **post_row(p),
        "writerFull": p.get("writerFull") or p.get("writer", ""),
        "postedAt": p.get("postedAt") or p.get("date", ""),
        "modifiedAt": p.get("modifiedAt", ""),
        "attachments": p.get("attachments") or [],
        "contentHtml": p.get("contentHtml"),
        "originalUrl": board_post_url(p["artNo"]),
        "newer": post_row(newer) if newer else None,
        "older": post_row(older) if older else None,
        "updatedAt": store.load_board()["updatedAt"],
    }
