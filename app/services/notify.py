"""Gmail SMTP 로 알림 메일 발송."""

import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from html import escape

from app.config import (
    BASE_URL,
    GMAIL_ADDRESS,
    GMAIL_APP_PASSWORD,
    MAIL_ENABLED,
    SES_SEARCH_URL,
)

_COLUMNS = [
    "기간",
    "구분",
    "기관명",
    "부서명",
    "근무지",
    "실습기간",
    "접수마감",
    "선발학과",
    "참여/모집",
    "실습지원금",
]
_TD = "padding:6px 10px;border:1px solid #ddd;vertical-align:top"
_TH = "padding:6px 10px;border:1px solid #ddd;background:#f3f4f6;white-space:nowrap"


class MailNotConfigured(RuntimeError):
    pass


def _cell(p: dict, col: str) -> str:
    if col == "기간":
        return p.get("periodShort") or p.get("period", "")
    if col == "선발학과":
        return ", ".join(p.get("선발학과") or [])
    if col == "참여/모집":
        return f"{p.get('참여인원') if p.get('참여인원') is not None else '-'} / {p.get('모집인원') or '-'}"
    return p.get(col, "") or ""


def _links() -> str:
    parts = [f"<a href='{SES_SEARCH_URL}'>SES 현장실습 기관조회</a>"]
    if BASE_URL:
        parts.insert(0, f"<a href='{BASE_URL}/'>공고 모아보기</a>")
    return (
        "<p style='color:#888;font-size:12px'>바로가기: " + " · ".join(parts) + "</p>"
    )


def _postings_html(postings: list[dict]) -> str:
    head = "".join(f"<th style='{_TH}'>{c}</th>" for c in _COLUMNS)
    rows = []
    for p in postings:
        cells = []
        for c in _COLUMNS:
            text = escape(str(_cell(p, c)))
            if c == "기관명" and BASE_URL:
                from app.services.views import company_slug  # 순환 import 방지

                text = f"<a href='{BASE_URL}/company/{company_slug(p.get('기관명', ''))}'>{text}</a>"
            cells.append(f"<td style='{_TD}'>{text}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return (
        f"<p>POSTECH SES 현장실습 기관에 <b>신규 공고 {len(postings)}건</b>이 등록되었습니다.</p>"
        f"<table style='border-collapse:collapse;font-size:13px'>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
        + _links()
    )


def _send(subject: str, body_html: str, recipients: list[str]) -> None:
    if not MAIL_ENABLED:
        raise MailNotConfigured(
            ".env 에 GMAIL_ADDRESS / GMAIL_APP_PASSWORD 가 없습니다."
        )
    msg = MIMEText(body_html, "html", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header("SES 알림", "utf-8")), GMAIL_ADDRESS))
    msg["To"] = ", ".join(recipients)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        s.sendmail(GMAIL_ADDRESS, recipients, msg.as_string())


def send_new_postings(postings: list[dict], recipients: list[str]) -> bool:
    """신규 공고를 recipients 전원에게 발송. 성공 시 True."""
    if not postings or not recipients:
        return False
    _send(
        f"[SES 알림] 신규 현장실습 기관 {len(postings)}건",
        _postings_html(postings),
        recipients,
    )
    print(f"[O] {len(recipients)}명에게 신규 공고 {len(postings)}건 발송 완료.")
    return True


def send_startup(recipients: list[str], interval_min: int) -> bool:
    """상주 모드 시작 알림(켜졌음) 메일 1회 발송."""
    if not recipients:
        return False
    body = (
        "<p>POSTECH SES 신규 현장실습 기관 알림이 <b>시작되었습니다</b>.</p>"
        f"<p>이제부터 <b>{interval_min}분</b>마다 새 공고를 점검하여, "
        "신규 공고가 올라오면 이 주소로 알림을 보냅니다.</p>" + _links()
    )
    _send("[SES 알림] 알림 시스템이 시작되었습니다", body, recipients)
    print(f"[O] 시작 알림을 {len(recipients)}명에게 발송했습니다.")
    return True


def send_test(recipient: str) -> None:
    body = (
        "<p>SES 공고 알림 <b>테스트 메일</b>입니다.</p>"
        "<p>이 메일을 받으셨다면 새 공고 알림도 이 주소로 정상 발송됩니다.</p>"
        + _links()
    )
    _send("[SES 알림] 테스트 메일", body, [recipient])
