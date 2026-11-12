"""
Builds the post images: one 4:5 card per real subject of the day's news, each a
real photo of that subject with a headline and one fact set over it.

The photo comes from Wikimedia Commons (real_photo.py). The layout is HTML
rendered by headless Chromium, which gives real typography; the copy comes from
content_generator as plain data.
"""
import base64
import html
from datetime import date
from io import BytesIO
from pathlib import Path

from image_generator import THEMES, _fetch_pexels_photo
from real_photo import find_photo

ROOT = Path(__file__).parent.parent
OUTPUT_DIR = ROOT / "output"
FONTS_DIR = ROOT / "assets" / "fonts"

# 4:5 portrait is the tallest ratio the LinkedIn feed shows uncropped.
WIDTH, HEIGHT = 1080, 1350
BRAND = "Rios-News"
MAX_IMAGES = 4

_CSS = """
@font-face { font-family: "Inter"; src: url(data:font/woff2;base64,%(inter)s) format("woff2"); font-weight: 100 900; }
@font-face { font-family: "Inter Tight"; src: url(data:font/woff2;base64,%(tight)s) format("woff2"); font-weight: 100 900; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: "Inter", "DejaVu Sans", sans-serif; color: #fff; background: #0B0D12; -webkit-font-smoothing: antialiased; }
.card { width: 1080px; height: 1350px; position: relative; overflow: hidden; background: #0B0D12; }
.card img { position: absolute; inset: 0; width: 100%%; height: 100%%; object-fit: cover; }
/* Portraits keep the face: the crop takes from the bottom of the frame first. */
.card img.tall { object-position: 50%% 18%%; }
.shade {
  position: absolute; inset: 0;
  background: linear-gradient(180deg, rgba(6,8,12,.62) 0%%, rgba(6,8,12,0) 16%%, rgba(6,8,12,0) 40%%, rgba(6,8,12,.86) 68%%, rgba(6,8,12,.97) 100%%);
}
.top {
  position: absolute; top: 60px; left: 72px; right: 72px; display: flex; justify-content: space-between; align-items: center;
  font: 700 24px/1 "Inter", sans-serif; letter-spacing: .16em; text-transform: uppercase;
}
.brand { background: var(--accent); color: #0B0D12; padding: 14px 20px; border-radius: 6px; }
.date { text-shadow: 0 2px 12px rgba(0,0,0,.9); }
.text { position: absolute; left: 72px; right: 72px; bottom: 60px; }
.kicker { font: 700 26px/1 "Inter", sans-serif; letter-spacing: .16em; text-transform: uppercase; color: var(--accent); margin-bottom: 26px; }
h1 { font: 800 96px/.98 "Inter Tight", "Inter", sans-serif; letter-spacing: -.028em; text-wrap: balance; margin-bottom: 30px; text-shadow: 0 2px 24px rgba(0,0,0,.55); }
h1.long { font-size: 80px; }
h1.xlong { font-size: 66px; }
.fact { font-size: 40px; line-height: 1.28; color: #E4E7EC; text-wrap: pretty; padding-left: 26px; border-left: 6px solid var(--accent); }
.meta { margin-top: 40px; display: flex; justify-content: space-between; gap: 32px; font-size: 21px; color: #A9B0BC; }
.meta b { color: #E4E7EC; font-weight: 600; }
.meta .credit { text-align: right; max-width: 700px; font-size: 18px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
"""


def _e(text) -> str:
    return html.escape(str(text or "").strip())


def _data_uri(image) -> str:
    # Nothing is gained by embedding more pixels than the 2x render shows.
    image = image.copy()
    image.thumbnail((2400, 3000))
    buf = BytesIO()
    image.save(buf, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _card_html(card: dict, photo: dict, today: date, accent: str, css: str) -> str:
    image = photo["image"]
    tall = "tall" if image.height > image.width * 1.05 else ""
    headline = card.get("headline", "")
    size = "xlong" if len(headline) > 64 else "long" if len(headline) > 40 else ""
    fact = f'<p class="fact">{_e(card.get("fact"))}</p>' if card.get("fact") else ""
    source = f'<span>Source: <b>{_e(card.get("source"))}</b></span>' if card.get("source") else "<span></span>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><style>{css}</style></head>
<body style="--accent:{accent}"><div class="card">
  <img class="{tall}" src="{_data_uri(image)}" alt="">
  <div class="shade"></div>
  <div class="top"><span class="brand">{BRAND}</span><span class="date">{today.strftime('%b %d, %Y')}</span></div>
  <div class="text">
    <div class="kicker">{_e(card.get('kicker'))}</div>
    <h1 class="{size}">{_e(headline)}</h1>
    {fact}
    <div class="meta">{source}<span class="credit">{_e(photo['credit'])}</span></div>
  </div>
</div></body></html>"""


def _launch(playwright):
    try:
        return playwright.chromium.launch()
    except Exception:
        # A dev machine usually has Chrome but not Playwright's own build.
        return playwright.chromium.launch(channel="chrome")


def render_cards(cards: list[dict], today: date, stem: str, stock_query: str = "") -> dict:
    """Render one image per card that has a real photo.

    Returns {"images": [Path], "credits": [str]}. A card whose subject has no
    freely licensed photo is left out rather than illustrated with something
    generic, except the first: the post needs one image, so the lead falls back
    to a stock photo and says so in the log.
    """
    from playwright.sync_api import sync_playwright

    used: set[str] = set()
    ready = []
    for i, card in enumerate(cards[:MAX_IMAGES]):
        photo = find_photo(card.get("subjects") or [], used)
        if photo is None and i == 0 and stock_query:
            stock = _fetch_pexels_photo(stock_query, today)
            if stock is not None:
                print("[photo] Lead image fell back to a stock photo")
                photo = {"image": stock, "credit": "Photo: Pexels", "page": "", "subject": stock_query}
        if photo is None:
            print(f"[photo] Left out the image for {card.get('headline', '')[:50]!r}: no real photo")
            if i == 0:
                break
            continue
        ready.append((card, photo))

    if not ready:
        raise RuntimeError("no photo found for the lead image")

    css = _CSS % {
        "inter": base64.b64encode((FONTS_DIR / "Inter-Variable.woff2").read_bytes()).decode("ascii"),
        "tight": base64.b64encode((FONTS_DIR / "InterTight-Variable.woff2").read_bytes()).decode("ascii"),
    }
    accent = "rgb(%d,%d,%d)" % THEMES[today.weekday()]["accent"]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    images, credits = [], []

    with sync_playwright() as p:
        browser = _launch(p)
        try:
            page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=2)
            for n, (card, photo) in enumerate(ready, 1):
                page.set_content(_card_html(card, photo, today, accent, css), wait_until="load")
                page.evaluate("document.fonts.ready")
                # The text block grows upward from the bottom; past this line it
                # would cover the face and run under the brand bar.
                top = page.evaluate("document.querySelector('.text').getBoundingClientRect().top")
                if top < 420:
                    raise RuntimeError(f"text on image {n} is too long for the frame (starts at {top:.0f}px)")
                path = OUTPUT_DIR / f"{stem}_{n:02d}.jpg"
                page.locator(".card").screenshot(path=str(path), type="jpeg", quality=92)
                images.append(path)
                if photo.get("page"):
                    credits.append(f"{photo['credit']}: {photo['page']}")
        finally:
            browser.close()

    print(f"[photo] {len(images)} image(s) rendered")
    return {"images": images, "credits": credits}


if __name__ == "__main__":
    # Layout preview with fixed sample copy: python src/photo_cards.py
    sample = [
        {"subjects": ["Jensen Huang"], "kicker": "Nvidia",
         "headline": "Nvidia board reportedly preparing to dismiss Jensen Huang",
         "fact": "The stock fell more than 7% in after-hours trading Wednesday.", "source": "The Verge"},
        {"subjects": ["Nvidia headquarters"], "kicker": "The investigation",
         "headline": "The board may act before its own probe ends",
         "fact": "Nvidia had retained former US attorney Joon H. Kim to investigate.", "source": "The Verge"},
    ]
    print(render_cards(sample, date.today(), "sample"))
