"""
SES 로그인 및 기업조회/상세 페이지 수집 (Playwright).
학생 로그인은 POSTECH 통합 SSO(ECDH+SEED)를 거치므로, 실제 브라우저로
로그인 폼을 구동하여 페이지 JS가 암호화를 처리하게 한다.
세션 쿠키는 state/storage.json 에 저장/재사용한다.

로그인 뒤의 목록·상세 요청은 브라우저 탭을 띄우지 않고 같은 쿠키를 쓰는
ctx.request 로 보낸다 - 페이지를 그리는 것보다 훨씬 빠르다.
"""

import os
import stat
import time

from app.config import SES_BASE, SES_DETAIL_URL, SES_SEARCH_URL, STATE_DIR, STORAGE_FILE
from app.services import parser, sso

# 공고 한 탭에 이보다 많은 페이지는 없다고 보고 끊는다 (무한 루프 방지).
_MAX_PAGES = 30
# 상세 요청 사이 간격 - SES 서버에 연달아 부담을 주지 않도록.
_DETAIL_DELAY = 0.2


class SesError(RuntimeError):
    pass


def _save_storage(ctx):
    ctx.storage_state(path=str(STORAGE_FILE))
    try:
        os.chmod(STORAGE_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 0600: 세션 쿠키 보호
    except OSError:
        pass


def _fill_and_login(page, sid, pw):
    """SES 메인 -> SSO 로그인 폼 구동. 성공 시 True."""
    page.goto(f"{SES_BASE}/index.do", wait_until="domcontentloaded")
    page.fill(".accordion_1 input[type=text]", sid)
    page.fill(".accordion_1 input[type=password]", pw)
    page.evaluate("index.topLogin('1')")  # SSOService.do 로 submit
    page.wait_for_load_state("networkidle", timeout=30000)

    if not sso.on_sso_page(page):
        return _is_logged_in(page)
    sso.sso_login(page, sid, pw)
    return True


def _is_logged_in(page):
    """보호 경로 접근으로 로그인 여부 확인."""
    page.goto(SES_SEARCH_URL, wait_until="domcontentloaded")
    url = page.url.rstrip("/")
    return "/student/" in url and url != f"{SES_BASE}/index.do"


def _get(ctx, url, params=None) -> str:
    resp = ctx.request.get(url, params=params, timeout=30000)
    if not resp.ok:
        raise SesError(f"SES 요청 실패 ({resp.status}): {url}")
    return resp.text()


def fetch_all(sid, pw, need_detail=None, headless=True):
    """진행 중인 모든 모집 기간 탭의 공고 목록과 필요한 상세를 가져온다.

    need_detail(row) -> bool : 이 공고의 상세를 새로 받아야 하는지. 없으면 전부 받음.

    반환: {"periods": [...], "rows": [...], "details": {jid: sections}}
    한 군데라도 실패하면 예외 - 일부만 받은 결과로 "공고가 사라졌다"고
    판단하면 안 되기 때문이다.
    """
    from playwright.sync_api import sync_playwright

    os.makedirs(STATE_DIR, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            storage = str(STORAGE_FILE) if STORAGE_FILE.exists() else None
            ctx = browser.new_context(storage_state=storage)
            page = ctx.new_page()
            page.on("dialog", lambda d: d.accept())

            # 1) 저장된 세션으로 바로 접근 시도, 안 되면 로그인
            logged_in = False
            if storage:
                try:
                    logged_in = _is_logged_in(page)
                except Exception:
                    logged_in = False
            if not logged_in:
                _fill_and_login(page, sid, pw)
                if not _is_logged_in(page):
                    raise SesError("로그인은 됐으나 기업조회 페이지 접근 실패.")
                _save_storage(ctx)

            first_html = page.content()
            tabs = parser.parse_tabs(first_html)
            if not tabs and not parser.is_list_page(first_html):
                raise SesError("기업조회 페이지 형식을 인식하지 못했습니다.")

            # 2) 탭(모집 기간)별 목록, 페이지 끝까지
            periods, rows = [], []
            for tab in tabs:
                page_no, total = 1, 1
                tab_rows = []
                while page_no <= min(total, _MAX_PAGES):
                    html = _get(
                        ctx,
                        SES_SEARCH_URL,
                        {
                            "jsSeq": tab["jsSeq"],
                            "currentList": "1",
                            "page": str(page_no),
                        },
                    )
                    if not parser.is_list_page(html):
                        raise SesError(
                            "목록 요청이 로그인 화면으로 돌아왔습니다 (세션 만료)."
                        )
                    found, total = parser.parse_list(html)
                    tab_rows.extend(found)
                    page_no += 1
                for r in tab_rows:
                    r["period"] = tab["name"]
                    r["periodShort"] = parser.short_period(tab["name"])
                periods.append(
                    {
                        "jsSeq": tab["jsSeq"],
                        "name": tab["name"],
                        "short": parser.short_period(tab["name"]),
                        "count": len(tab_rows),
                    }
                )
                rows.extend(tab_rows)

            # 3) 상세
            details = {}
            for r in rows:
                if need_detail is not None and not need_detail(r):
                    continue
                html = _get(ctx, SES_DETAIL_URL, {"jidSeq": r["jid"]})
                if parser.is_detail_page(html):
                    details[r["jid"]] = parser.parse_detail(html)
                time.sleep(_DETAIL_DELAY)

            _save_storage(ctx)  # 갱신된 세션 쿠키 보존
            return {"periods": periods, "rows": rows, "details": details}
        finally:
            browser.close()
