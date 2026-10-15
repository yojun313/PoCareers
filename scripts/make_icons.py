"""홈 화면 아이콘(PNG) 만들기 - 빨간 바탕에 'Careers'.

Commeet 와 같은 방식입니다: 아이콘은 모서리 없는 정사각형으로 만들고(iOS·안드로이드가
알아서 둥글게 깎음), 브라우저 탭용 favicon.svg 만 모서리를 둥글게 둡니다.
글꼴을 이 서버의 Chromium 으로 그려 PNG 로 굽습니다.

  uv run scripts/make_icons.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.paths import STATIC_DIR  # noqa: E402

TEXT = "Careers"
RED = "#c80150"


def svg(rounded: bool) -> str:
    rx = ' rx="230"' if rounded else ""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
  <rect width="1024" height="1024"{rx} fill="{RED}"/>
  <text x="512" y="512" text-anchor="middle" dominant-baseline="central"
        font-family="-apple-system, 'Segoe UI', 'Helvetica Neue', Arial, 'Liberation Sans', sans-serif"
        font-weight="800" font-size="212" fill="#ffffff" letter-spacing="-6"
        textLength="760" lengthAdjust="spacingAndGlyphs">{TEXT}</text>
</svg>
"""


def main():
    from playwright.sync_api import sync_playwright

    (STATIC_DIR / "favicon.svg").write_text(svg(rounded=True), encoding="utf-8")
    square = svg(rounded=False)
    out = STATIC_DIR / "icons"
    out.mkdir(exist_ok=True)
    sizes = {
        "apple-touch-icon.png": 180,
        "icon-192.png": 192,
        "icon-512.png": 512,
        "favicon-32.png": 32,
    }
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, size in sizes.items():
            page = browser.new_page(viewport={"width": size, "height": size})
            page.set_content(
                f"<style>html,body{{margin:0}}svg{{display:block;width:{size}px;height:{size}px}}</style>{square}"
            )
            page.screenshot(path=str(out / name), omit_background=True)
            page.close()
            print(f"[O] icons/{name} ({size}px)")
        browser.close()
    print("[O] favicon.svg")


if __name__ == "__main__":
    main()
