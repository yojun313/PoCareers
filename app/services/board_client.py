"""POSTECH 전자게시판 '인턴 및 채용 공고' 수집 (Playwright).

SES 와 같은 통합 SSO 로 로그인합니다. 세션 쿠키는 SES 와 따로
state/board_storage.json 에 저장/재사용합니다. 로그인 뒤 목록·본문은
브라우저 탭 없이 같은 쿠키를 쓰는 ctx.request 로 받습니다.
"""

import os
import stat
import time

from app.config import (
    BOARD_BASE,
    BOARD_CONTENT_URL,
    BOARD_EXCLUDE,
    BOARD_FIRST_REMARK,
    BOARD_LIST_URL,
    BOARD_NO,
    BOARD_POST_URL,
    BOARD_STORAGE_FILE,
    STATE_DIR,
    board_list_page_url,
)
from app.services import board_parser, sso

# 웹 화면에 보관하는 분류별 최근 글 수 (페이지당 10건 -> 처음 한 번 10쪽까지 읽어 채움).
PER_CATEGORY = 100
ARCHIVE_SIZE = (
    PER_CATEGORY * 3
)  # 처음 채울 때 기준 (보관함은 지난 글도 지우지 않습니다)
# 한 번 점검에 분류마다 읽는 목록 페이지 상한.
MAX_PAGES = 10
# 한 번 점검에 본문을 받는 글 수 상한 (새 글 제외). 보관함을 처음 채울 때
# SES 처럼 수백 건을 한꺼번에 요청하지 않고 점검마다 나눠 받습니다.
DETAIL_BATCH = 40
_CONTENT_DELAY = 0.2


class BoardError(RuntimeError):
    pass


def _save_storage(ctx):
    ctx.storage_state(path=str(BOARD_STORAGE_FILE))
    try:
        os.chmod(BOARD_STORAGE_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        pass


def _list_html(ctx, page_no: int, remark_no: str) -> str | None:
    """분류 하나의 목록 HTML. 세션이 없으면 SSO 로 보내는 짧은 페이지가 와서 None."""
    resp = ctx.request.get(
        BOARD_LIST_URL,
        params={
            "boardNo": BOARD_NO,
            "remarkNo": remark_no,
            "currentPage": str(page_no),
        },
        timeout=30000,
    )
    if not resp.ok:
        raise BoardError(f"게시판 요청 실패 ({resp.status})")
    html = resp.text()
    return html if board_parser.is_board_list(html) else None


def _login(ctx, sid, pw):
    page = ctx.new_page()
    page.on("dialog", lambda d: d.accept())
    page.goto(board_list_page_url(), wait_until="networkidle")
    if sso.on_sso_page(page):
        sso.sso_login(page, sid, pw)
    page.close()


def _detail(ctx, art_no: str) -> dict:
    """글 한 건: 머리(작성자·등록일·조회수·첨부) + 정리한 본문 + 메일용 미리보기."""
    params = {"boardNo": BOARD_NO, "artNo": art_no}
    head = ctx.request.get(BOARD_POST_URL, params=params, timeout=30000)
    body = ctx.request.get(BOARD_CONTENT_URL, params=params, timeout=30000)
    if not head.ok or not body.ok:
        raise BoardError(f"게시글 {art_no} 요청 실패 ({head.status}/{body.status})")
    raw = body.text()
    info = board_parser.parse_board_post(head.text())
    info["contentHtml"] = board_parser.sanitize_content(raw, BOARD_BASE)
    info["snippet"] = board_parser.parse_board_content(raw)
    return info


def _walk(
    ctx, remark_no, first_html, known, newest_known, have_count
) -> tuple[list, int | None]:
    """분류 하나의 목록을 필요한 만큼 넘기며 읽습니다.

    - 보관함에 이 분류 글이 PER_CATEGORY 건보다 적으면 그만큼 찰 때까지 (처음 한 번)
    - 페이지 전체가 새 글이면 다음 페이지에도 새 글이 있을 수 있으니 계속
    """
    listed = board_parser.parse_board_list(first_html)
    total = board_parser.parse_board_total(first_html)
    backfill = have_count < PER_CATEGORY * 0.9
    page_no = 1
    while page_no < MAX_PAGES and listed:
        page_rows = listed[-10:]
        more_new = known is not None and all(
            int(r["artNo"]) > newest_known for r in page_rows
        )
        if backfill and len(listed) >= PER_CATEGORY:
            backfill = False
        if not (backfill or more_new):
            break
        page_no += 1
        html = _list_html(ctx, page_no, remark_no)
        rows = board_parser.parse_board_list(html) if html else []
        if not rows:
            break
        listed.extend(rows)
    return listed, total


def fetch_board(
    sid, pw, known: set[str] | None, have: dict, need_detail, headless=True
) -> dict:
    """게시판을 분류별로 읽어 새 글을 찾고, 웹 화면용 보관함을 채울 글 내용을 받습니다.

    BOARD_EXCLUDE 분류(교내채용)는 목록 요청조차 하지 않습니다 - 게시판이 분류별
    목록(remarkNo)을 따로 주므로, 나머지 분류만 하나씩 읽습니다.

    known : 이미 알림 판단을 끝낸 글 번호들. None 이면 최초 실행(전부 기준선).
    have  : 보관함에 있는 글 {artNo: 분류}. 분류별로 PER_CATEGORY 건까지 채웁니다.
    need_detail(artNo) -> bool : 이 글의 본문을 (다시) 받아야 하는지.

    새 글은 '알던 글 중 가장 큰 번호보다 큰 번호'만 칩니다 - 게시판 글 번호는
    계속 커지므로, 보관함을 채우려고 뒤 페이지를 읽어도 옛 글이 새 글로 잡히지 않습니다.

    반환: {"total", "categories", "listed": 읽은 목록 행(최신 먼저),
           "new": 새 글(오래된 순, 본문 포함), "details": {artNo: 내용}}
    """
    from playwright.sync_api import sync_playwright

    os.makedirs(STATE_DIR, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            storage = str(BOARD_STORAGE_FILE) if BOARD_STORAGE_FILE.exists() else None
            ctx = browser.new_context(storage_state=storage)

            html = _list_html(ctx, 1, BOARD_FIRST_REMARK)
            if html is None:
                _login(ctx, sid, pw)
                html = _list_html(ctx, 1, BOARD_FIRST_REMARK)
                if html is None:
                    raise BoardError(
                        "로그인은 됐으나 게시판 목록에 접근하지 못했습니다."
                    )
                _save_storage(ctx)

            tabs = [
                t
                for t in board_parser.parse_board_categories(html)
                if t["name"] not in BOARD_EXCLUDE
            ]
            if not tabs:
                raise BoardError("게시판 분류 탭을 인식하지 못했습니다.")

            newest_known = max((int(k) for k in known or () if k.isdigit()), default=0)
            listed, total = [], 0
            for tab in tabs:
                first = (
                    html
                    if tab["remarkNo"] == BOARD_FIRST_REMARK
                    else _list_html(ctx, 1, tab["remarkNo"])
                )
                if first is None:
                    raise BoardError(f"'{tab['name']}' 목록에 접근하지 못했습니다.")
                have_count = sum(1 for c in have.values() if c == tab["name"])
                rows, count = _walk(
                    ctx, tab["remarkNo"], first, known, newest_known, have_count
                )
                # 분류 페이지에도 다른 분류 글이 섞여 나오는 일은 없지만, 혹시 몰라 한 번 더 거릅니다
                listed.extend(r for r in rows if r["category"] not in BOARD_EXCLUDE)
                total += count or 0
            listed.sort(key=lambda r: int(r["artNo"]), reverse=True)

            new = []
            if known is not None:
                new = [
                    r
                    for r in listed
                    if int(r["artNo"]) > newest_known and r["artNo"] not in known
                ]

            # 새 글은 메일에 본문이 들어가야 하니 먼저, 나머지는 한 번에 DETAIL_BATCH 건씩
            details = {}
            todo = [r["artNo"] for r in new]
            # 이번에 목록에서 본 글 + 보관함에 있는 글 중 본문이 없는 것, 최신 글부터
            pool = {r["artNo"] for r in listed} | {
                k for k, c in have.items() if c not in BOARD_EXCLUDE
            }
            todo += [
                a
                for a in sorted(pool, key=int, reverse=True)
                if a not in todo and need_detail(a)
            ][:DETAIL_BATCH]
            for art_no in todo:
                details[art_no] = _detail(ctx, art_no)
                time.sleep(_CONTENT_DELAY)
            for r in new:
                r.update(details[r["artNo"]])

            _save_storage(ctx)
            new.reverse()  # 오래된 글부터
            return {
                "total": total,
                "categories": [t["name"] for t in tabs],
                "listed": listed,
                "new": new,
                "details": details,
            }
        finally:
            browser.close()
