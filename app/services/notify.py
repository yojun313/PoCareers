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
    BOARD_NAME,
    SES_SEARCH_URL,
    board_list_page_url,
    board_post_url,
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
    "지원/모집",
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
    if col == "지원/모집":
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


def _send(
    subject: str, body_html: str, recipients: list[str], sender_name: str = "SES 알림"
) -> None:
    if not MAIL_ENABLED:
        raise MailNotConfigured(
            ".env 에 GMAIL_ADDRESS / GMAIL_APP_PASSWORD 가 없습니다."
        )
    msg = MIMEText(body_html, "html", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header(sender_name, "utf-8")), GMAIL_ADDRESS))
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


def _applicant_html(items: list[tuple[dict, int, int]]) -> str:
    from app.services.views import company_slug, posting_view  # 순환 import 방지

    blocks = []
    for p, before, count in items:
        v = posting_view(p)
        name = escape(f"{p.get('기관명', '')} · {p.get('부서명', '')}")
        if BASE_URL:
            name = (
                f"<a href='{BASE_URL}/company/{company_slug(p.get('기관명', ''))}' "
                f"style='color:#c80150;text-decoration:none'>{name}</a>"
            )
        quota = p.get("모집인원")
        facts = " · ".join(
            x
            for x in (
                v.get("periodShort") or v.get("period"),
                f"모집 {quota}명" if quota else "",
                f"경쟁률 {v['ratio']}:1" if v.get("ratio") is not None else "",
                f"마감 {p.get('접수마감')}" if p.get("접수마감") else "",
            )
            if x
        )
        blocks.append(
            "<div style='margin:0 0 12px;padding:12px 14px;border:1px solid #ddd;border-radius:6px'>"
            f"<div style='font-size:15px;font-weight:bold;margin-bottom:6px'>{name}</div>"
            f"<div style='font-size:14px;margin-bottom:6px'>지원자 {before}명 → <b>{count}명</b> "
            f"<span style='color:#c80150;font-weight:bold'>(+{count - before})</span></div>"
            f"<div style='color:#666;font-size:12px'>{escape(facts)}</div></div>"
        )
    return (
        f"<p>관심 공고 <b>{len(items)}건</b>에 지원자가 늘었습니다.</p>"
        + "".join(blocks)
        + _links()
    )


def send_applicant_alert(items: list[tuple[dict, int, int]], recipient: str) -> None:
    """관심 공고 지원자 증가 알림. items: [(공고, 이전 지원자 수, 지금 지원자 수)]."""
    p, before, count = items[0]
    more = f" 외 {len(items) - 1}건" if len(items) > 1 else ""
    _send(
        f"[지원자 알림] {p.get('기관명', '')} {p.get('부서명', '')} "
        f"지원자 {count}명 (+{count - before}){more}",
        _applicant_html(items),
        [recipient],
        sender_name="SES 지원자 알림",
    )
    print(f"[O] {recipient} 에게 관심 공고 지원자 알림 {len(items)}건 발송 완료.")


def _board_html(posts: list[dict]) -> str:
    blocks = []
    for p in posts:
        tags = " · ".join(
            x
            for x in (
                p.get("category"),
                p.get("writer"),
                p.get("date"),
                "첨부파일" if p.get("hasFile") else "",
                "본문 이미지" if p.get("hasImage") else "",
            )
            if x
        )
        snippet = escape(p.get("snippet") or "").replace("\n", "<br>")
        if not snippet and p.get("hasImage"):
            snippet = "<span style='color:#888'>본문이 이미지로 되어 있습니다. 게시판에서 확인하세요.</span>"
        blocks.append(
            "<div style='margin:0 0 14px;padding:12px 14px;border:1px solid #ddd;border-radius:6px'>"
            f"<div style='font-size:15px;font-weight:bold;margin-bottom:4px'>"
            f"<a href='{board_post_url(p['artNo'])}' style='color:#c80150;text-decoration:none'>{escape(p.get('title', ''))}</a></div>"
            f"<div style='color:#666;font-size:12px;margin-bottom:8px'>{escape(tags)}</div>"
            + (
                f"<div style='font-size:13px;line-height:1.6;color:#333'>{snippet}</div>"
                if snippet
                else ""
            )
            + "</div>"
        )
    return (
        f"<p>POSTECH 전자게시판 <b>{escape(BOARD_NAME)}</b>에 <b>새 글 {len(posts)}건</b>이 올라왔습니다.</p>"
        + "".join(blocks)
        + "<p style='color:#888;font-size:12px'>게시글은 POVIS 로그인 후 볼 수 있습니다. "
        f"바로가기: <a href='{board_list_page_url()}'>{escape(BOARD_NAME)} 게시판</a></p>"
    )


def send_board_posts(posts: list[dict], recipients: list[str]) -> bool:
    """전자게시판 새 글을 recipients 에게 발송. 성공 시 True."""
    if not posts or not recipients:
        return False
    first = posts[-1].get("title", "")
    more = f" 외 {len(posts) - 1}건" if len(posts) > 1 else ""
    _send(
        f"[채용 공고] {first}{more}",
        _board_html(posts),
        recipients,
        sender_name="POSTECH 채용 알림",
    )
    print(f"[O] {len(recipients)}명에게 게시판 새 글 {len(posts)}건 발송 완료.")
    return True


def send_startup(recipients: list[str], interval_min: int) -> bool:
    """상주 모드 시작 알림(켜졌음) 메일 1회 발송."""
    if not recipients:
        return False
    body = (
        "<p>POSTECH 공고 알림이 <b>시작되었습니다</b>.</p>"
        f"<p>이제부터 <b>{interval_min}분</b>마다 SES 현장실습 공고와 전자게시판 "
        f"'{escape(BOARD_NAME)}'을 점검하여, 받기로 설정한 알림을 이 주소로 보냅니다.</p>"
        + _links()
    )
    _send("[SES 알림] 알림 시스템이 시작되었습니다", body, recipients)
    print(f"[O] 시작 알림을 {len(recipients)}명에게 발송했습니다.")
    return True


def send_test(recipient: str) -> None:
    body = (
        "<p>SES 공고 알림 <b>테스트 메일</b>입니다.</p>"
        "<p>이 메일을 받으셨다면 SES 공고·전자게시판 새 글 알림도 이 주소로 정상 발송됩니다.</p>"
        + _links()
    )
    _send("[SES 알림] 테스트 메일", body, [recipient])
