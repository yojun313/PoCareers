"""MongoDB 연결과 컬렉션.

컬렉션 (사람이 Compass/mongosh 로 열어 봐도 읽히도록 한국어 원문 필드 그대로):
  postings         SES 공고 1건 = 문서 1개 (_id = SES 공고 번호 jid). 내려간 공고도 지우지 않습니다.
  posting_changes  공고 목록 값이 바뀐 기록 (마감 연장, 모집 인원 변경 등)
  periods          모집 기간 탭 (_id = jsSeq). SES 에서 내려간 기간도 ended=true 로 남깁니다.
  board_posts      전자게시판 '인턴 및 채용 공고' 글 (_id = 글 번호 artNo, 정수)
  recipients       메일 수신자 (_id = 소문자 이메일)
  watches          관심 공고별 마지막으로 알린 지원자 수 (_id = jid)
  notified         알림 판단을 끝낸 공고/글 (_id = "ses:<jid>" / "board:<artNo>")
  mail_log         보낸 메일 기록
  check_log        점검 1회 기록 (SES/게시판, 주기/마감 직전/수동)
  meta             수집 시각, 게시판 분류 등 (_id = "ses" / "board")

시각은 모두 UTC datetime 으로 저장합니다 (Compass 에서 날짜로 보입니다).
"""

from urllib.parse import quote_plus

from pymongo import ASCENDING, DESCENDING, MongoClient

from app.config import (
    MONGO_AUTH_DB,
    MONGO_DB,
    MONGO_HOST,
    MONGO_PASSWORD,
    MONGO_PORT,
    MONGO_USERNAME,
)

_auth = (
    f"{quote_plus(MONGO_USERNAME)}:{quote_plus(MONGO_PASSWORD)}@"
    if MONGO_USERNAME
    else ""
)
client = MongoClient(
    f"mongodb://{_auth}{MONGO_HOST}:{MONGO_PORT}/?authSource={MONGO_AUTH_DB}",
    tz_aware=True,
    serverSelectionTimeoutMS=5000,
)
db = client[MONGO_DB]

postings_col = db["postings"]
posting_changes_col = db["posting_changes"]
periods_col = db["periods"]
board_posts_col = db["board_posts"]
recipients_col = db["recipients"]
watches_col = db["watches"]
notified_col = db["notified"]
mail_log_col = db["mail_log"]
check_log_col = db["check_log"]
meta_col = db["meta"]


def ensure_indexes() -> None:
    postings_col.create_index([("active", DESCENDING), ("deadlineAt", ASCENDING)])
    postings_col.create_index([("기관명", ASCENDING)])
    postings_col.create_index([("jsSeq", ASCENDING)])
    posting_changes_col.create_index([("jid", ASCENDING), ("at", DESCENDING)])
    board_posts_col.create_index([("category", ASCENDING), ("_id", DESCENDING)])
    notified_col.create_index([("kind", ASCENDING), ("at", DESCENDING)])
    mail_log_col.create_index([("at", DESCENDING)])
    check_log_col.create_index([("startedAt", DESCENDING)])
    check_log_col.create_index([("kind", ASCENDING), ("startedAt", DESCENDING)])
