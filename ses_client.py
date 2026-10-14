"""
SES 로그인 및 기업조회 페이지 HTML 획득 (Playwright).
학생 로그인은 POSTECH 통합 SSO(ECDH+SEED)를 거치므로, 실제 브라우저로
로그인 폼을 구동하여 페이지 JS가 암호화를 처리하게 한다.
세션 쿠키는 state/storage.json 에 저장/재사용한다.
"""
import os
import stat
from config import BASE, SEARCH_URL, STATE_DIR, STORAGE


def _save_storage(ctx):
    ctx.storage_state(path=STORAGE)
    try:
        os.chmod(STORAGE, stat.S_IRUSR | stat.S_IWUSR)  # 0600: 세션 쿠키 보호
    except OSError:
        pass


def _fill_and_login(page, sid, pw):
    """SES 메인 -> SSO 로그인 폼 구동. 성공 시 True."""
    page.goto(f"{BASE}/index.do", wait_until="domcontentloaded")
    page.fill(".accordion_1 input[type=text]", sid)
    page.fill(".accordion_1 input[type=password]", pw)
    page.evaluate("index.topLogin('1')")           # SSOService.do 로 submit
    page.wait_for_load_state("networkidle", timeout=30000)

    if "sso.postech.ac.kr" not in page.url:
        return _is_logged_in(page)

    page.wait_for_selector("#login_id", timeout=15000)
    # ECDH 키교환(client_calkey) 준비 대기
    page.wait_for_function(
        "() => typeof client_calkey !== 'undefined' && client_calkey "
        "&& client_calkey.length > 0", timeout=15000)
    page.fill("#login_id", sid)
    page.fill("#login_pwd", pw)
    resp = page.evaluate("() => loginModule.auth('/sso/usr/postech/login/auth', lang)")
    code = resp.get("code") if isinstance(resp, dict) else None

    if code in ("SS0001", "SS0009"):
        with page.expect_navigation(timeout=30000):
            page.evaluate(
                "() => { $('form[name=loginForm]').first()"
                ".attr('action','/sso/usr/postech/login/link').submit(); }")
        page.wait_for_load_state("networkidle", timeout=30000)
        return True
    if code == "SS0030":
        raise RuntimeError("2차 인증(OTP)이 요구됩니다 (SS0030). 교내망에서 시도하거나 OTP 설정 필요.")
    raise RuntimeError(f"로그인 실패: SSO 응답 코드 {code} (아이디/비밀번호 확인).")


def _is_logged_in(page):
    """보호 경로 접근으로 로그인 여부 확인."""
    page.goto(SEARCH_URL, wait_until="domcontentloaded")
    url = page.url.rstrip("/")
    return "/student/" in url and url != f"{BASE}/index.do"


def get_search_html(sid, pw, headless=True):
    """
    기업조회 페이지 HTML 반환.
    저장된 세션을 먼저 쓰고, 만료됐으면 재로그인한다.
    """
    from playwright.sync_api import sync_playwright

    os.makedirs(STATE_DIR, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        storage = STORAGE if os.path.exists(STORAGE) else None
        ctx = browser.new_context(storage_state=storage)
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())

        # 1) 저장된 세션으로 바로 접근 시도
        logged_in = False
        if storage:
            try:
                logged_in = _is_logged_in(page)
            except Exception:
                logged_in = False

        # 2) 안 되면 로그인
        if not logged_in:
            _fill_and_login(page, sid, pw)
            if not _is_logged_in(page):
                browser.close()
                raise RuntimeError("로그인은 됐으나 기업조회 페이지 접근 실패.")
            _save_storage(ctx)

        html = page.content()
        browser.close()
        return html
