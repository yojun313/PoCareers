"""Gmail SMTP 로 신규 공고 알림 메일 발송."""
import json
import os
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr

from config import RECIPIENTS
from parser import KEY_COLS


def load_recipients(path=RECIPIENTS):
    """JSON 리스트 형식의 수신 이메일 목록 로드."""
    if not os.path.exists(path):
        print(f"[!] 수신자 파일 {path} 가 없습니다. recipients.example.json 을 복사해 만드세요.")
        return []
    data = json.load(open(path, encoding="utf-8"))
    if not isinstance(data, list):
        print(f"[!] {path} 는 이메일 문자열의 JSON 배열이어야 합니다.")
        return []
    return [e.strip() for e in data if isinstance(e, str) and e.strip()]


def _html_body(postings):
    rows = []
    for p in postings:
        cells = "".join(
            f"<td style='padding:6px 10px;border:1px solid #ddd'>{p.get(c,'')}</td>"
            for c in ["구분", "기관명", "부서명", "근무지", "실습기간",
                      "접수마감", "선발학과", "참여/모집", "실습지원금"])
        rows.append(f"<tr>{cells}</tr>")
    head = "".join(
        f"<th style='padding:6px 10px;border:1px solid #ddd;background:#f3f4f6'>{c}</th>"
        for c in ["구분", "기관명", "부서명", "근무지", "실습기간",
                  "접수마감", "선발학과", "참여/모집", "실습지원금"])
    return (
        f"<p>POSTECH SES 현장실습 기관에 <b>신규 공고 {len(postings)}건</b>이 등록되었습니다.</p>"
        f"<table style='border-collapse:collapse;font-size:13px'>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
        f"<p style='color:#888;font-size:12px'>바로가기: "
        f"<a href='https://ses.postech.ac.kr/student/manage/search/index.do'>"
        f"현장실습 기관조회</a></p>")


def send(env, postings, recipients):
    """postings(신규 공고 리스트)를 recipients 전원에게 발송. 성공 시 True."""
    if not postings or not recipients:
        return False
    sender = env["GMAIL_ADDRESS"]
    pw = env["GMAIL_APP_PASSWORD"]

    msg = MIMEText(_html_body(postings), "html", "utf-8")
    msg["Subject"] = Header(f"[SES 알림] 신규 현장실습 기관 {len(postings)}건", "utf-8")
    msg["From"] = formataddr((str(Header("SES 알림", "utf-8")), sender))
    msg["To"] = ", ".join(recipients)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(sender, pw)
        s.sendmail(sender, recipients, msg.as_string())
    print(f"[O] {len(recipients)}명에게 신규 공고 {len(postings)}건 발송 완료.")
    return True
