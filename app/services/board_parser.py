"""POSTECH 전자게시판 HTML 파싱 (인턴 및 채용 공고).

- parse_board_list: /board/viewBoard.do 의 글 목록 표.
- parse_board_content: /board/viewPostArtContent.do (본문만 담긴 iframe) 의 글자.
"""

import re

from bs4 import BeautifulSoup

from app.services.parser import _block_text, _clean

_VIEW_POST = re.compile(r"viewPost\(\s*'(\d+)'")
_SNIPPET_MAX = 600


def parse_board_list(html: str) -> list[dict]:
    """[{artNo, no, category, title, writer, date, hasFile, hasImage}] - 화면 순서(최신 먼저)."""
    soup = BeautifulSoup(html, "html.parser")
    posts = []
    for tr in soup.select("table tbody tr"):
        link = tr.select_one("td.title a[href]")
        m = _VIEW_POST.search(link["href"]) if link else None
        if not m:
            continue
        tds = tr.find_all("td", recursive=False)
        title = link.select_one(".txt")
        posts.append(
            {
                "artNo": m.group(1),
                # 상단 고정 공지는 번호 대신 '공지' 같은 글자가 들어갑니다
                "no": _clean(tds[0].get_text()) if tds else "",
                "category": _clean(tr.select_one("td.remark_mo").get_text())
                if tr.select_one("td.remark_mo")
                else "",
                "title": _clean((title or link).get_text()),
                "writer": _clean(tr.select_one("td.writer_mo").get_text())
                if tr.select_one("td.writer_mo")
                else "",
                "date": _clean(tr.select_one("td.date_mo").get_text())
                if tr.select_one("td.date_mo")
                else "",
                "hasFile": link.select_one(".file") is not None,
                "hasImage": link.select_one(".img_add") is not None,
            }
        )
    return posts


def is_board_list(html: str) -> bool:
    return "viewPost(" in html or "게시판 목록" in html


def parse_board_content(html: str) -> str:
    """본문 앞부분 (메일 미리보기용). 이미지뿐인 글이면 빈 문자열."""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style"]):
        t.decompose()
    if soup.body is None:
        return ""
    text = _block_text(soup.body)
    if len(text) > _SNIPPET_MAX:
        text = text[:_SNIPPET_MAX].rstrip() + " …"
    return text


_TOTAL = re.compile(r"[\d,]+")


def parse_board_total(html: str) -> int | None:
    """목록 위 '총 10,577 건'."""
    soup = BeautifulSoup(html, "html.parser")
    el = soup.select_one(".total-results .count")
    m = _TOTAL.search(el.get_text()) if el else None
    return int(m.group().replace(",", "")) if m else None


_REMARK = re.compile(r"remarkNo=(\d+)")


def parse_board_categories(html: str) -> list[dict]:
    """분류 탭 ('전체' 제외), 게시판 순서대로: [{"name": "인턴십", "remarkNo": "0"}, ...]."""
    soup = BeautifulSoup(html, "html.parser")
    tabs = []
    for a in soup.select(".tab-box ul li a[href]"):
        m = _REMARK.search(a["href"])
        name = _clean(a.get_text())
        if m and name:
            tabs.append({"name": name, "remarkNo": m.group(1)})
    return tabs


def parse_board_post(html: str) -> dict:
    """글 보기(/board/viewPost.do) 머리 부분: 작성자(소속 포함)·등록/수정 시각·조회수·첨부 이름."""
    soup = BeautifulSoup(html, "html.parser")
    info = {
        "writerFull": "",
        "postedAt": "",
        "modifiedAt": "",
        "views": None,
        "attachments": [],
    }
    status = soup.select_one(".board_view .board_status")
    if status is not None:
        for li in status.select("li"):
            tits = [_clean(t.get_text()) for t in li.select(".tit")]
            vals = [_clean(v.get_text()) for v in li.select(".date, .view")]
            if not tits and vals:
                info["writerFull"] = vals[0]
            for t, v in zip(tits, vals):
                if t == "등록일":
                    info["postedAt"] = v
                elif t == "수정":
                    info["modifiedAt"] = v
                elif t == "조회수":
                    info["views"] = int(v) if v.isdigit() else None
    for li in soup.select(".file_wrap dd li"):
        name = _clean("".join(li.find_all(string=True, recursive=False)))
        if name:
            info["attachments"].append(name)
    return info


# ── 본문 정리 ───────────────────────────────────────
# 게시판 본문은 작성자가 편집기로 쓴 HTML 입니다. 우리 화면에 그대로 넣으려면
# 스크립트·이벤트 속성·폼 같은 건 걷어 내고, 서식(굵게·색·표·이미지)만 남깁니다.

_DROP = {
    "script",
    "style",
    "iframe",
    "frame",
    "object",
    "embed",
    "form",
    "input",
    "button",
    "select",
    "textarea",
    "link",
    "meta",
    "head",
    "title",
    "svg",
    "math",
    "noscript",
    "template",
    "base",
    "audio",
    "video",
    "source",
    "applet",
}
_KEEP = {
    "p",
    "br",
    "div",
    "span",
    "b",
    "strong",
    "i",
    "em",
    "u",
    "s",
    "strike",
    "del",
    "ins",
    "sub",
    "sup",
    "font",
    "small",
    "big",
    "mark",
    "ul",
    "ol",
    "li",
    "dl",
    "dt",
    "dd",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "td",
    "th",
    "colgroup",
    "col",
    "caption",
    "figure",
    "figcaption",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "pre",
    "code",
    "hr",
    "a",
    "img",
    "center",
}
_ATTRS = {
    "*": {"style", "align", "valign"},
    "a": {"href"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan", "width"},
    "th": {"colspan", "rowspan", "width"},
    "col": {"span", "width"},
    "font": {"color", "size", "face"},
    "table": {"width", "border", "cellpadding", "cellspacing"},
}
# 화면 밖으로 튀어나오거나 페이지를 덮는 속성, 외부 리소스를 부르는 값은 뺍니다.
_BAD_STYLE_PROPS = {
    "position",
    "z-index",
    "behavior",
    "-moz-binding",
    "top",
    "left",
    "right",
    "bottom",
}
_BAD_STYLE_VALUE = re.compile(r"url\s*\(|expression|javascript:|@import", re.I)


def _abs_url(url: str, base: str) -> str | None:
    url = (url or "").strip()
    if not url:
        return None
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        url = base + url
    low = url.lower()
    if low.startswith("http://board.postech.ac.kr"):
        url = "https://" + url[len("http://") :]
    elif not (
        low.startswith("https://")
        or low.startswith("http://")
        or low.startswith("mailto:")
    ):
        return None
    return url


def _clean_style(style: str) -> str:
    kept = []
    for decl in style.split(";"):
        prop, _, value = decl.partition(":")
        prop = prop.strip().lower()
        if not prop or not value.strip():
            continue
        if prop in _BAD_STYLE_PROPS or _BAD_STYLE_VALUE.search(value):
            continue
        kept.append(f"{prop}: {value.strip()}")
    return "; ".join(kept)


def sanitize_content(html: str, base: str) -> str:
    """본문 iframe HTML -> 우리 페이지에 넣어도 안전한 HTML 조각."""
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body or soup
    for el in body.find_all(_DROP):
        el.decompose()
    for el in body.find_all(
        string=lambda s: s.__class__.__name__ in ("Comment", "Doctype")
    ):
        el.extract()
    for el in list(body.find_all(True)):
        if el.name not in _KEEP:
            el.unwrap()
            continue
        allowed = _ATTRS["*"] | _ATTRS.get(el.name, set())
        for attr in list(el.attrs):
            if attr not in allowed:
                del el[attr]
        if el.get("style"):
            style = _clean_style(el["style"])
            if style:
                el["style"] = style
            else:
                del el["style"]
        if el.name == "a":
            href = _abs_url(el.get("href", ""), base)
            if href:
                el["href"] = href
                el["target"] = "_blank"
                el["rel"] = "noopener noreferrer"
            elif "href" in el.attrs:
                del el["href"]
        if el.name == "img":
            src = _abs_url(el.get("src", ""), base)
            if not src or src.startswith("mailto:"):
                el.decompose()
                continue
            el["src"] = src
            el["loading"] = "lazy"
            el["referrerpolicy"] = "no-referrer"
    return "".join(str(c) for c in body.contents).strip()
