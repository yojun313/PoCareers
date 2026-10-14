"""기업조회 페이지 HTML -> 공고(기업) 목록 파싱."""
import re
import hashlib
from html.parser import HTMLParser

# 표 컬럼 순서 (tbl_type01)
COLUMNS = ["구분", "기관명", "부서명", "근무지", "실습기간",
           "접수마감", "선발학과", "참여/모집", "실습지원금", "지원"]
# 공고를 고유 식별하는 키 컬럼 (변동값인 '참여/모집', '지원'은 제외)
KEY_COLS = ["기관명", "부서명", "근무지", "실습기간", "접수마감", "선발학과", "실습지원금"]


class _TableParser(HTMLParser):
    """class="tbl_type01" 테이블의 tbody 행/셀을 추출."""
    def __init__(self):
        super().__init__()
        self.in_target = False
        self.depth = 0
        self.in_tbody = False
        self.in_td = self.in_th = False
        self.rows, self.cur, self.buf = [], None, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self.depth += 1
            if "tbl_type01" in (a.get("class") or ""):
                self.in_target = True
                self.target_depth = self.depth
        elif self.in_target:
            if tag == "tbody":
                self.in_tbody = True
            elif tag == "tr" and self.in_tbody:
                self.cur = []
            elif tag in ("td", "th") and self.cur is not None:
                self.in_td = True
                self.buf = []
            elif tag == "br" and self.in_td:
                self.buf.append(" ")

    def handle_endtag(self, tag):
        if tag == "table":
            if self.in_target and self.depth == getattr(self, "target_depth", -1):
                self.in_target = self.in_tbody = False
            self.depth -= 1
        elif self.in_target:
            if tag in ("td", "th") and self.in_td:
                self.in_td = False
                txt = re.sub(r"\s+", " ", "".join(self.buf)).strip()
                self.cur.append(txt)
            elif tag == "tr" and self.cur is not None:
                self.rows.append(self.cur)
                self.cur = None

    def handle_data(self, data):
        if self.in_td:
            self.buf.append(data)


def parse_postings(html):
    """공고 목록을 dict 리스트로 반환. 각 dict 에 안정적 'key' 포함."""
    p = _TableParser()
    p.feed(html)
    postings = []
    for row in p.rows:
        if not row:
            continue
        text = " ".join(row)
        if "데이터가 없습니다" in text or "NO_RESULT" in text:
            continue
        if len(row) < 7:          # 머리글/빈 행 방어
            continue
        rec = {COLUMNS[i]: (row[i] if i < len(row) else "")
               for i in range(len(COLUMNS))}
        key_src = "|".join(rec.get(c, "") for c in KEY_COLS)
        rec["key"] = hashlib.sha1(key_src.encode("utf-8")).hexdigest()[:16]
        postings.append(rec)
    return postings
