"""SES 페이지 HTML 파싱.

- parse_tabs: 기관조회 상단의 모집 기간 탭 (예: "2026 포스텍 동계 SES (8주~9주)").
  같은 시즌이라도 실습 기간별로 탭이 나뉘어 있고, 탭마다 공고 목록이 따로입니다.
- parse_list: 탭 하나의 공고 표(tbl_type01)와 페이지 수.
- parse_detail: 기관명을 누르면 뜨는 상세(/jobInternDetail.do)의 항목들.
"""

import hashlib
import re
from datetime import date

from bs4 import BeautifulSoup, NavigableString, Tag

# 예전(웹 화면 이전) 알림기가 공고를 식별하던 컬럼. seen.json 의 옛 키를
# 새 키(jid)로 옮길 때만 씁니다 - app/services/store.py 참고.
_LEGACY_KEY_COLS = [
    "기관명",
    "부서명",
    "근무지",
    "실습기간",
    "접수마감",
    "선발학과",
    "실습지원금",
]

_DETAIL_CALL = re.compile(r"jobInternDetail\(\s*'(\d+)'\s*,\s*'(\d+)'")
_TAB_CALL = re.compile(r"setJsSeq\(\s*'\d*'\s*,\s*'(\d+)'")
_SHORT_PERIOD = re.compile(r"\(([^)]*)\)\s*$")
_LIST_DATES = re.compile(r"(\d{2})\.(\d{2})\.(\d{2})\s*~\s*(\d{2})\.(\d{2})\.(\d{2})")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _block_text(node: Tag) -> str:
    """셀 내용을 줄바꿈을 살린 글자로. <br>, <div>, <p>, <li> 경계가 줄이 됩니다."""
    parts: list[str] = []

    def _break():
        # 블록 경계는 줄바꿈 하나 - 이미 줄이 바뀌어 있으면 더하지 않습니다.
        # (<br><br> 처럼 의도한 빈 줄은 그대로 둡니다)
        if parts and not "".join(parts[-2:]).rstrip(" \t\xa0").endswith("\n"):
            parts.append("\n")

    def walk(el, pre):
        for child in el.children:
            if isinstance(child, NavigableString):
                if child.__class__.__name__ == "Comment":
                    continue
                text = str(child)
                # SES 는 <p> 안만 white-space: pre-wrap 입니다. 그 밖의 소스 줄바꿈은
                # 화면에 보이지 않으므로 공백으로 칩니다 (안 그러면 <br> 마다 빈 줄이 생김).
                parts.append(text if pre else text.replace("\n", " "))
            elif isinstance(child, Tag):
                if child.name == "br":
                    parts.append("\n")
                    continue
                block = child.name in ("div", "p", "li", "ul", "tr")
                if block:
                    _break()
                walk(child, pre or child.name == "p")
                if block:
                    _break()

    walk(node, node.name == "p")
    lines = [_clean(line) for line in "".join(parts).split("\n")]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def short_period(name: str) -> str:
    """'2026 포스텍 동계 SES (8주~9주)' -> '8주~9주'. 괄호가 없으면 전체 이름."""
    m = _SHORT_PERIOD.search(name or "")
    return m.group(1).strip() if m else (name or "")


def list_dates(text: str) -> tuple[str, str] | tuple[None, None]:
    """목록의 '26.12.28~27.02.26' -> ('2026-12-28', '2027-02-26')."""
    m = _LIST_DATES.search(text or "")
    if not m:
        return None, None
    y1, m1, d1, y2, m2, d2 = (int(x) for x in m.groups())
    try:
        start = date(2000 + y1, m1, d1)
        end = date(2000 + y2, m2, d2)
    except ValueError:
        return None, None
    return start.isoformat(), end.isoformat()


def parse_tabs(html: str) -> list[dict]:
    """진행 중인 모집 기간 탭 목록: [{"jsSeq": "182", "name": "...", "active": bool}]."""
    soup = BeautifulSoup(html, "html.parser")
    tabs = []
    for li in soup.select("div.tabs ul.tab1 > li"):
        a = li.find("a", onclick=True)
        if not a:
            continue
        m = _TAB_CALL.search(a["onclick"])
        if not m:
            continue
        tabs.append(
            {
                "jsSeq": m.group(1),
                "name": _clean(a.get_text()),
                "active": "tabActive" in (li.get("class") or []),
            }
        )
    return tabs


def _legacy_key(tds: list[Tag]) -> str:
    """예전 알림기와 똑같이 계산한 키 - 셀 글자를 이어 붙이고 공백만 정리."""

    def text(td):
        td = BeautifulSoup(str(td), "html.parser").td
        for br in td.find_all("br"):
            br.replace_with(" ")
        return _clean(td.get_text(""))

    cols = [
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
    vals = {c: text(td) for c, td in zip(cols, tds)}
    src = "|".join(vals.get(c, "") for c in _LEGACY_KEY_COLS)
    return hashlib.sha1(src.encode("utf-8")).hexdigest()[:16]


def parse_list(html: str) -> tuple[list[dict], int]:
    """공고 표 -> (행 목록, 전체 페이지 수)."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.tbl_type01")
    rows = []
    if table is not None:
        for tr in table.select("tbody > tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 9:
                continue  # '데이터가 없습니다' 등
            link = tds[1].find("a", onclick=True)
            m = _DETAIL_CALL.search(link["onclick"]) if link else None
            if not m:
                continue
            depts = [_clean(d.get_text()) for d in tds[6].find_all("div")]
            if not depts:
                depts = [x for x in _clean(tds[6].get_text()).split(" ") if x]
            filled, _, quota = _clean(tds[7].get_text()).partition("/")
            row = {
                "jid": m.group(1),
                "jsSeq": m.group(2),
                "구분": _clean(tds[0].get_text()),
                "기관명": _clean(tds[1].get_text()),
                "부서명": _clean(tds[2].get_text()),
                "근무지": _clean(tds[3].get_text()),
                "실습기간": _clean(tds[4].get_text()),
                "접수마감": _clean(tds[5].get_text()),
                "선발학과": depts,
                "참여인원": _to_int(filled),
                "모집인원": _to_int(quota),
                "실습지원금": _clean(tds[8].get_text()),
            }
            row["startDate"], row["endDate"] = list_dates(row["실습기간"])
            row["legacyKey"] = _legacy_key(tds)
            rows.append(row)

    pages = 1
    for a in soup.select("div.paging a.paging_pager"):
        n = _to_int(a.get_text())
        if n and n > pages:
            pages = n
    return rows, pages


def _to_int(text: str):
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def _cell_value(td: Tag) -> str:
    """상세 칸의 값. 체크박스/라디오는 체크된 항목의 라벨만 남깁니다."""
    td = BeautifulSoup(str(td), "html.parser").td  # 원본을 건드리지 않도록 복사
    checked: list[str] = []
    for inp in td.find_all("input"):
        label = inp.find_next_sibling("label")
        if inp.get("type") in ("checkbox", "radio"):
            if inp.has_attr("checked") and label is not None:
                checked.append(_clean(label.get_text()))
            if label is not None:
                label.decompose()
        inp.decompose()
    for a in td.find_all("a"):
        href = a.get("href") or ""
        if "download" in href:
            a.replace_with("첨부 있음 (SES 로그인 후 다운로드)")
    text = _block_text(td)
    if checked:
        joined = ", ".join(checked)
        if text.endswith(":"):
            return f"{text} {joined}"
        return f"{text} ({joined})" if text else joined
    return text


def parse_detail(html: str) -> list[dict]:
    """상세 페이지 -> [{"title": 섹션명, "rows": [[항목, 값], ...]}].

    표(tbl_type02)마다 한 섹션입니다. 표 첫 줄이 th.tbl_tit 이면 그 글자가
    섹션 제목이 됩니다 (예: '실습직무'). 한 줄에 th/td 쌍이 둘 있는 경우
    (기관명 | 홈페이지)도 각각의 항목으로 풉니다.
    """
    soup = BeautifulSoup(html, "html.parser")
    sections = []
    for i, table in enumerate(soup.select("table.tbl_type02")):
        title = "기본 정보" if i == 0 else "추가 정보"
        rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"], recursive=False)
            if (
                len(cells) == 1
                and cells[0].name == "th"
                and "tbl_tit" in (cells[0].get("class") or [])
            ):
                title = _clean(cells[0].get_text())
                continue
            label = None
            for cell in cells:
                if cell.name == "th":
                    label = _clean(_block_text(cell).replace("\n", " "))
                elif label is not None:
                    value = _cell_value(cell)
                    rows.append([label, value if value else "-"])
                    label = None
        if rows:
            sections.append({"title": title, "rows": rows})
    return sections


def is_list_page(html: str) -> bool:
    return "tbl_type01" in html


def is_detail_page(html: str) -> bool:
    return "tbl_type02" in html
