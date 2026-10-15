"""POSTECH 통합 SSO 로그인 (SES·전자게시판 공용).

로그인 폼은 ECDH 키교환 + SEED 암호화를 페이지 JS 가 처리하므로, 실제
브라우저(Playwright)로 폼을 구동합니다. 호출하는 쪽이 페이지를 SSO 로그인
화면(sso.postech.ac.kr)까지 데려온 뒤 sso_login 을 부릅니다.
"""


class SsoError(RuntimeError):
    pass


def on_sso_page(page) -> bool:
    return "sso.postech.ac.kr" in page.url


def sso_login(page, sid, pw) -> None:
    """SSO 로그인 화면에서 로그인하고 원래 서비스로 돌아갈 때까지 기다립니다."""
    page.wait_for_selector("#login_id", timeout=15000)
    # ECDH 키교환(client_calkey) 준비 대기
    page.wait_for_function(
        "() => typeof client_calkey !== 'undefined' && client_calkey "
        "&& client_calkey.length > 0",
        timeout=15000,
    )
    page.fill("#login_id", sid)
    page.fill("#login_pwd", pw)
    resp = page.evaluate("() => loginModule.auth('/sso/usr/postech/login/auth', lang)")
    code = resp.get("code") if isinstance(resp, dict) else None

    if code in ("SS0001", "SS0009"):
        with page.expect_navigation(timeout=30000):
            page.evaluate(
                "() => { $('form[name=loginForm]').first()"
                ".attr('action','/sso/usr/postech/login/link').submit(); }"
            )
        page.wait_for_load_state("networkidle", timeout=30000)
        return
    if code == "SS0030":
        raise SsoError(
            "2차 인증(OTP)이 요구됩니다 (SS0030). 교내망에서 시도하거나 OTP 설정 필요."
        )
    raise SsoError(f"로그인 실패: SSO 응답 코드 {code} (아이디/비밀번호 확인).")
