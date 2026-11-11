"""
Builds the LinkedIn carousel: a 4:5 slide deck rendered from HTML by headless
Chromium, saved as one PDF (the document post) plus one JPEG per slide (the
multi-image fallback and the preview artifact).

The deck content comes from content_generator as plain data. Nothing here
writes copy: this module only lays out what it is given.
"""
import base64
import html
import os
from datetime import date
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

from image_generator import THEMES, _cover_crop, _fetch_pexels_photo

ROOT = Path(__file__).parent.parent
OUTPUT_DIR = ROOT / "output"
FONTS_DIR = ROOT / "assets" / "fonts"

# 4:5 portrait is the tallest ratio the LinkedIn feed shows uncropped, so it
# takes more of the screen than the old 1080x1080 card.
WIDTH, HEIGHT = 1080, 1350
BRAND = "Rios-News"

_CSS = """
@font-face { font-family: "Inter"; src: url(data:font/woff2;base64,%(inter)s) format("woff2"); font-weight: 100 900; }
@font-face { font-family: "Inter Tight"; src: url(data:font/woff2;base64,%(tight)s) format("woff2"); font-weight: 100 900; }
@page { size: 1080px 1350px; margin: 0; }
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { background: #0B0D12; }
body { font-family: "Inter", "DejaVu Sans", sans-serif; color: #F4F5F7; -webkit-font-smoothing: antialiased; }
.slide {
  width: 1080px; height: 1350px; position: relative; overflow: hidden;
  break-after: page; page-break-after: always;
  background: #0B0D12; padding: 84px 84px 0 84px;
  display: flex; flex-direction: column;
}
.slide::before {            /* accent rule down the left edge */
  content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 10px; background: var(--accent);
}
.kicker {
  font: 700 26px/1 "Inter", sans-serif; letter-spacing: .16em; text-transform: uppercase;
  color: var(--accent); flex: none;
}
h1, h2, .value { font-family: "Inter Tight", "Inter", sans-serif; font-weight: 800; letter-spacing: -.025em; }
h2 { font-size: 84px; line-height: 1.02; margin-bottom: 64px; text-wrap: balance; }
h2.long { font-size: 66px; }
.body { font-size: 46px; line-height: 1.32; color: #D5D9E0; text-wrap: pretty; }
.body.long { font-size: 38px; }
.main { flex: 1; display: flex; flex-direction: column; justify-content: center; padding-bottom: 40px; min-height: 0; }
.foot {
  height: 112px; flex: none; display: flex; align-items: center; justify-content: space-between;
  border-top: 2px solid #232836; font-size: 24px; color: #8F97A6; letter-spacing: .02em;
}
.foot b { color: #C9CED8; font-weight: 600; }
.foot .src { max-width: 720px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pager { font-variant-numeric: tabular-nums; font-weight: 600; color: #C9CED8; }

/* cover */
.cover { padding: 0; }
.cover::before { display: none; }
.cover .photo { height: 600px; flex: none; position: relative; background: var(--bg2) center/cover no-repeat; }
.cover .photo::after {
  content: ""; position: absolute; inset: 0;
  background: linear-gradient(180deg, rgba(11,13,18,.55) 0%%, rgba(11,13,18,0) 28%%, rgba(11,13,18,0) 55%%, #0B0D12 100%%);
}
.cover .top {
  position: absolute; z-index: 2; top: 64px; left: 84px; right: 84px;
  display: flex; justify-content: space-between; align-items: center;
  font: 700 24px/1 "Inter", sans-serif; letter-spacing: .16em; text-transform: uppercase;
}
.cover .top .brand { background: var(--accent); color: #0B0D12; padding: 14px 20px; border-radius: 6px; }
.cover .top .date { color: #F4F5F7; text-shadow: 0 2px 12px rgba(0,0,0,.8); }
.cover .text { padding: 0 84px 36px; flex: 1; display: flex; flex-direction: column; justify-content: center; position: relative; z-index: 2; }
.cover .kicker { margin-bottom: 32px; }
.cover h1 { font-size: 104px; line-height: .98; text-wrap: balance; margin-bottom: 36px; }
.cover h1.long { font-size: 84px; }
.cover h1.xlong { font-size: 68px; }
.cover .dek { font-size: 40px; line-height: 1.3; color: #C3C8D2; text-wrap: pretty; }
.cover .foot { margin: 0 84px; }
.swipe { background: #F4F5F7; color: #0B0D12; font-weight: 700; padding: 14px 24px; border-radius: 999px; font-size: 24px; }

/* stat */
.value { font-size: 250px; line-height: .92; color: var(--accent); margin: 0 0 34px -8px; white-space: nowrap; }
.value.long { font-size: 190px; }
.value.xlong { font-size: 136px; }
.label { font: 700 54px/1.12 "Inter Tight", sans-serif; letter-spacing: -.01em; margin-bottom: 44px; text-wrap: balance; }
.rule { width: 120px; height: 6px; background: #2A3040; margin-bottom: 44px; }

/* bars */
.bars { display: flex; flex-direction: column; gap: 48px; margin-bottom: 60px; }
.bar .name { font-size: 34px; color: #AEB5C2; margin-bottom: 14px; }
.bar .row { display: flex; align-items: center; gap: 24px; }
.bar .fill { height: 96px; border-radius: 10px; background: #2A3040; min-width: 14px; }
.bar.top .fill { background: var(--accent); }
.bar .num { font: 800 60px/1 "Inter Tight", sans-serif; letter-spacing: -.02em; white-space: nowrap; }
.bar.top .num { color: var(--accent); }
.note { font-size: 38px; line-height: 1.35; color: #AEB5C2; text-wrap: pretty; }

/* points + roundup */
.points { display: flex; flex-direction: column; gap: 56px; }
.point { display: flex; gap: 32px; align-items: flex-start; }
.point .n { font: 800 48px/1.2 "Inter Tight", sans-serif; color: var(--accent); width: 64px; flex: none; font-variant-numeric: tabular-nums; }
.point p { font-size: 46px; line-height: 1.3; color: #E6E9EE; text-wrap: pretty; }
.items { display: flex; flex-direction: column; }
.item { padding: 52px 0; border-top: 2px solid #232836; }
.item:first-child { border-top: 0; padding-top: 0; }
.item .tag { font: 700 24px/1 "Inter", sans-serif; letter-spacing: .14em; text-transform: uppercase; color: var(--accent); margin-bottom: 16px; }
.item p { font-size: 46px; line-height: 1.28; color: #E6E9EE; text-wrap: pretty; }

/* closing */
.closing h2 { font-size: 104px; margin-top: 64px; }
.closing .outlets { font-size: 34px; line-height: 1.5; color: #AEB5C2; margin-top: 12px; }
.closing .follow { font: 700 56px/1.15 "Inter Tight", sans-serif; }
.closing .follow span { color: var(--accent); }
"""


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _e(text) -> str:
    return html.escape(str(text or "").strip())


def _size_class(text: str, long_at: int, xlong_at: int | None = None) -> str:
    n = len(text or "")
    if xlong_at and n > xlong_at:
        return "xlong"
    return "long" if n > long_at else ""


def _cover_photo_uri(query: str, today: date, accent: tuple) -> str:
    """Stock photo for the cover, recoloured to the day's accent.

    A random stock photo in full colour makes each day look like a different
    publication. Mapping it to one dark tone and the accent keeps the cover
    recognisable while the subject still changes every day.
    """
    photo = _fetch_pexels_photo(query, today)
    if photo is None:
        return ""
    img = _cover_crop(photo, WIDTH, 600)
    gray = ImageOps.autocontrast(ImageOps.grayscale(img), cutoff=1)
    light = tuple(min(255, int(c * 0.55 + 255 * 0.45)) for c in accent)
    mid = tuple(int(c * 0.55) for c in accent)
    toned = ImageOps.colorize(gray, black=(8, 10, 16), white=light, mid=mid)
    buf = BytesIO()
    toned.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _foot(source: str, page: int, total: int) -> str:
    left = f'<span class="src">Source: <b>{_e(source)}</b></span>' if source else f"<span>{BRAND}</span>"
    return f'<div class="foot">{left}<span class="pager">{page:02d} / {total:02d}</span></div>'


def _slide_cover(deck: dict, today: date, photo_uri: str, total: int) -> str:
    style = f' style="background-image:url({photo_uri})"' if photo_uri else ""
    headline = deck.get("headline", "")
    return f"""
<section class="slide cover">
  <div class="top"><span class="brand">{BRAND}</span><span class="date">{today.strftime('%b %d, %Y')}</span></div>
  <div class="photo"{style}></div>
  <div class="text">
    <div class="kicker">AI Daily Digest</div>
    <h1 class="{_size_class(headline, 48, 70)}">{_e(headline)}</h1>
    <p class="dek">{_e(deck.get('dek'))}</p>
  </div>
  <div class="foot"><span>{_e(deck.get('username', ''))}</span><span class="swipe">Swipe &rarr;</span></div>
</section>"""


def _slide_stat(s: dict, page: int, total: int) -> str:
    value, body = s.get("value", ""), s.get("body", "")
    return f"""
<section class="slide">
  <div class="kicker">{_e(s.get('kicker'))}</div>
  <div class="main">
  <div class="value {_size_class(value, 6, 9)}">{_e(value)}</div>
  <div class="label">{_e(s.get('label'))}</div>
  <div class="rule"></div>
  <p class="body {_size_class(body, 210)}">{_e(body)}</p>
  </div>
  {_foot(s.get('source', ''), page, total)}
</section>"""


def _slide_bars(s: dict, page: int, total: int) -> str:
    bars = s.get("bars") or []
    peak = max((b["value"] for b in bars), default=0) or 1
    rows = []
    for b in bars:
        # 620px is the widest a bar can be and still leave room for its number.
        width = max(14, int(620 * b["value"] / peak))
        top = " top" if b.get("highlight") else ""
        rows.append(
            f'<div class="bar{top}"><div class="name">{_e(b.get("label"))}</div>'
            f'<div class="row"><div class="fill" style="width:{width}px"></div>'
            f'<div class="num">{_e(b.get("display"))}</div></div></div>'
        )
    title = s.get("title", "")
    return f"""
<section class="slide">
  <div class="kicker">{_e(s.get('kicker'))}</div>
  <div class="main">
  <h2 class="{_size_class(title, 52)}">{_e(title)}</h2>
  <div class="bars">{''.join(rows)}</div>
  <p class="note">{_e(s.get('body'))}</p>
  </div>
  {_foot(s.get('source', ''), page, total)}
</section>"""


def _slide_points(s: dict, page: int, total: int) -> str:
    points = "".join(
        f'<div class="point"><span class="n">{i:02d}</span><p>{_e(p)}</p></div>'
        for i, p in enumerate(s.get("points") or [], 1)
    )
    title = s.get("title", "")
    return f"""
<section class="slide">
  <div class="kicker">{_e(s.get('kicker'))}</div>
  <div class="main">
  <h2 class="{_size_class(title, 52)}">{_e(title)}</h2>
  <div class="points">{points}</div>
  </div>
  {_foot(s.get('source', ''), page, total)}
</section>"""


def _slide_roundup(items: list[dict], page: int, total: int) -> str:
    rows = "".join(
        f'<div class="item"><div class="tag">{_e(i.get("source"))}</div><p>{_e(i.get("text"))}</p></div>'
        for i in items
    )
    return f"""
<section class="slide">
  <div class="kicker">Also in the news</div>
  <div class="main">
  <div class="items">{rows}</div>
  </div>
  {_foot('', page, total)}
</section>"""


def _slide_closing(deck: dict, page: int, total: int) -> str:
    outlets = " &middot; ".join(_e(o) for o in deck.get("outlets") or [])
    return f"""
<section class="slide closing">
  <div class="kicker">Sources</div>
  <h2>Every link is in the first comment.</h2>
  <p class="outlets">{outlets}</p>
  <div class="main"></div>
  <p class="follow">A new digest every morning.<br><span>{_e(deck.get('username', ''))}</span></p>
  <div style="height:64px"></div>
  {_foot('', page, total)}
</section>"""


_RENDERERS = {"stat": _slide_stat, "bars": _slide_bars, "points": _slide_points}


def build_html(deck: dict, today: date, photo_uri: str = "") -> tuple[str, int]:
    """Returns (html, slide_count)."""
    content = [s for s in deck.get("slides") or [] if s.get("type") in _RENDERERS]
    roundup = deck.get("roundup") or []
    total = 1 + len(content) + (1 if roundup else 0) + 1

    theme = THEMES[today.weekday()]
    accent = "rgb(%d,%d,%d)" % theme["accent"]
    bg2 = "rgb(%d,%d,%d)" % theme["bg_bottom"]

    parts = [_slide_cover(deck, today, photo_uri, total)]
    page = 2
    for s in content:
        parts.append(_RENDERERS[s["type"]](s, page, total))
        page += 1
    if roundup:
        parts.append(_slide_roundup(roundup, page, total))
        page += 1
    parts.append(_slide_closing(deck, page, total))

    css = _CSS % {
        "inter": _b64(FONTS_DIR / "Inter-Variable.woff2"),
        "tight": _b64(FONTS_DIR / "InterTight-Variable.woff2"),
    }
    doc = (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><style>{css}</style></head>'
        f'<body style="--accent:{accent};--bg2:{bg2}">{"".join(parts)}</body></html>'
    )
    return doc, total


def _launch(playwright):
    try:
        return playwright.chromium.launch()
    except Exception:
        # A dev machine usually has Chrome but not Playwright's own build.
        return playwright.chromium.launch(channel="chrome")


def render_carousel(deck: dict, today: date, stem: str, image_query: str = "") -> dict:
    """Render the deck. Returns {"pdf": Path, "images": [Path, ...]}.

    Raises on any failure: the caller falls back to the single Pillow card.
    """
    from playwright.sync_api import sync_playwright

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    accent = THEMES[today.weekday()]["accent"]
    photo_uri = _cover_photo_uri(image_query, today, accent) if image_query else ""
    doc, total = build_html(deck, today, photo_uri)

    html_path = OUTPUT_DIR / f"{stem}.html"
    html_path.write_text(doc, encoding="utf-8")
    pdf_path = OUTPUT_DIR / f"{stem}.pdf"
    images: list[Path] = []

    with sync_playwright() as p:
        browser = _launch(p)
        try:
            page = browser.new_page(
                viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=2
            )
            page.set_content(doc, wait_until="load")
            page.evaluate("document.fonts.ready")

            # A slide whose text runs past its frame is clipped silently by
            # overflow:hidden, so measure before trusting the render.
            overflowing = page.evaluate(
                """() => [...document.querySelectorAll('.slide')].map((s, i) => {
                    const foot = s.querySelector('.foot').getBoundingClientRect();
                    const box = s.getBoundingClientRect();
                    const main = s.querySelector('.main, .text');
                    const squeezed = main && main.scrollHeight > main.clientHeight + 1;
                    return foot.bottom > box.bottom + 1 || s.scrollWidth > s.clientWidth + 1 || squeezed ? i + 1 : 0;
                }).filter(Boolean)"""
            )
            if overflowing:
                raise RuntimeError(f"text overflows the frame on slide(s) {overflowing}")

            for i, section in enumerate(page.query_selector_all(".slide"), 1):
                path = OUTPUT_DIR / f"{stem}_{i:02d}.jpg"
                section.screenshot(path=str(path), type="jpeg", quality=92)
                images.append(path)

            page.pdf(
                path=str(pdf_path),
                width=f"{WIDTH}px",
                height=f"{HEIGHT}px",
                print_background=True,
                prefer_css_page_size=True,
            )
        finally:
            browser.close()

    if len(images) != total:
        raise RuntimeError(f"rendered {len(images)} slides, expected {total}")
    print(f"[carousel] {total} slides → {pdf_path.name} ({pdf_path.stat().st_size // 1024} KB)")
    return {"pdf": pdf_path, "images": images}


if __name__ == "__main__":
    # Layout preview with fixed sample content: python src/carousel.py [photo.jpg]
    import sys

    sample = {
        "username": "@danquiell",
        "headline": "Anthropic prices its IPO at up to $1.404 trillion",
        "dek": "825 million shares at $70 to $78, with Google and Nvidia putting in $10 billion each.",
        "slides": [
            {"type": "stat", "kicker": "The valuation", "value": "$1.404T",
             "label": "Fully diluted, at the top of the range",
             "body": "The range is $70 to $78 a share. The top figure assumes underwriters exercise every option.",
             "source": "Reuters"},
            {"type": "bars", "kicker": "In context", "title": "Where the number sits",
             "bars": [{"label": "Valuation, May 2026", "value": 965, "display": "$965B"},
                      {"label": "IPO, top of range", "value": 1404, "display": "$1.404T", "highlight": True},
                      {"label": "Target reported weeks ago", "value": 2000, "display": "$2T"}],
             "body": "Above the last private round, below the target it reportedly pursued.",
             "source": "Reuters"},
            {"type": "points", "kicker": "The mechanics", "title": "Who is buying in",
             "points": ["825 million Class A shares, underwritten by Goldman Sachs and Morgan Stanley.",
                        "$26 billion in non-voting Class N stock placed with seven chip and cloud companies.",
                        "Proceeds land between $84.6 billion and $93.7 billion."],
             "source": "Reuters"},
        ],
        "roundup": [
            {"source": "Yahoo News", "text": "UK chip startup Fractile reached a $7 billion valuation in its latest round."},
            {"source": "Wccftech", "text": "Microsoft is pushing back on a possible US ban on Chinese optical AI components."},
        ],
        "outlets": ["Reuters", "Yahoo News", "Wccftech", "TechCrunch"],
    }
    uri = ""
    if len(sys.argv) > 1:
        accent = THEMES[date.today().weekday()]["accent"]
        _fetch_pexels_photo = lambda q, t: Image.open(sys.argv[1]).convert("RGB")  # noqa: E731
        uri = _cover_photo_uri("x", date.today(), accent)
    os.environ.setdefault("PEXELS_API_KEY", "")
    doc, n = build_html(sample, date.today(), uri)
    from playwright.sync_api import sync_playwright

    OUTPUT_DIR.mkdir(exist_ok=True)
    with sync_playwright() as p:
        b = _launch(p)
        pg = b.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        pg.set_content(doc)
        pg.evaluate("document.fonts.ready")
        for i, sec in enumerate(pg.query_selector_all(".slide"), 1):
            sec.screenshot(path=str(OUTPUT_DIR / f"sample_{i:02d}.jpg"), type="jpeg", quality=88)
        pg.pdf(path=str(OUTPUT_DIR / "sample.pdf"), width="1080px", height="1350px",
               print_background=True, prefer_css_page_size=True)
        b.close()
    print(f"{n} sample slides in {OUTPUT_DIR}")
