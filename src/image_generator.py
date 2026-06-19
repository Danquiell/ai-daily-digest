"""
Generates a 1080x1080 LinkedIn card.

Primary style: a real, topic-relevant photo (fetched from Pexels by visual
query) as the hero image, darkened just enough for a short punchy teaser to pop.
If Pexels is unavailable (no API key, network error, no results), it falls back
to the legacy text-on-gradient card so the pipeline never fails to produce an
image.
"""
import json
import os
import textwrap
import urllib.parse
import urllib.request
from datetime import date
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUTPUT_DIR = Path(__file__).parent.parent / "output"
ASSETS_DIR = Path(__file__).parent.parent / "assets" / "fonts"

WIDTH, HEIGHT = 1080, 1080
BG_TOP = (8, 8, 16)

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
PEXELS_FALLBACK_QUERY = "artificial intelligence technology"

# One accent color per weekday (Mon=0 … Sun=6) — keeps a recognizable identity
# while the photo changes every day.
THEMES = [
    {"accent": (59, 130, 246),  "bg_bottom": (12, 20, 42),  "dim": (90, 115, 175)},   # Mon — blue
    {"accent": (139, 92, 246),  "bg_bottom": (20, 12, 42),  "dim": (115, 90, 175)},   # Tue — purple
    {"accent": (16, 185, 129),  "bg_bottom": (8, 32, 22),   "dim": (70, 135, 100)},   # Wed — emerald
    {"accent": (245, 158, 11),  "bg_bottom": (32, 20, 6),   "dim": (155, 120, 65)},   # Thu — amber
    {"accent": (34, 211, 238),  "bg_bottom": (6, 30, 38),   "dim": (65, 145, 165)},   # Fri — cyan
    {"accent": (244, 63, 94),   "bg_bottom": (36, 6, 16),   "dim": (155, 70, 90)},    # Sat — rose
    {"accent": (129, 140, 248), "bg_bottom": (16, 14, 44),  "dim": (105, 105, 180)},  # Sun — indigo
]

TEXT_WHITE = (255, 255, 255)
TEXT_GRAY = (210, 210, 222)

SOURCE_COLORS = {
    "openai":       (16, 163, 127),
    "google":       (66, 133, 244),
    "anthropic":    (214, 148, 20),
    "meta":         (24, 119, 242),
    "the verge":    (240, 50, 50),
    "hacker news":  (255, 100, 0),
    "techcrunch":   (25, 185, 100),
    "ars technica": (240, 130, 0),
    "9to5google":   (52, 120, 230),
    "wired":        (180, 180, 200),
    "bloomberg":    (220, 50, 50),
    "reuters":      (255, 165, 0),
    "bbc":          (187, 25, 25),
}


# ── Font / text helpers ────────────────────────────────────────────────────
def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        [
            ASSETS_DIR / "Inter-Bold.ttf",
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
            Path("/System/Library/Fonts/Helvetica.ttc"),
        ]
        if bold
        else [
            ASSETS_DIR / "Inter-Regular.ttf",
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
            Path("/System/Library/Fonts/Helvetica.ttc"),
        ]
    )
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except Exception:
                pass
    return ImageFont.load_default()


def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _text_h(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[3] - bbox[1]


def _draw_text_shadow(draw, pos, text, font, fill, shadow=(0, 0, 0), offset=3):
    """Draw text with a soft dark shadow so it stays readable over any photo."""
    x, y = pos
    for dx, dy in ((offset, offset), (offset, -offset), (-offset, offset), (-offset, -offset)):
        draw.text((x + dx, y + dy), text, font=font, fill=shadow)
    draw.text((x, y), text, font=font, fill=fill)


# ── Pexels photo fetch ──────────────────────────────────────────────────────
def _fetch_pexels_photo(query: str, today: date) -> Image.Image | None:
    """Fetch a topic-relevant photo from Pexels. Returns an RGB image or None."""
    api_key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not api_key:
        print("[image] No PEXELS_API_KEY set — using fallback text card")
        return None

    for q in (query, PEXELS_FALLBACK_QUERY):
        q = (q or "").strip()
        if not q:
            continue
        try:
            # No orientation filter: landscape photos are far more abundant and
            # _cover_crop squares them off cleanly — maximizes real-photo hit rate.
            url = PEXELS_SEARCH_URL + "?" + urllib.parse.urlencode(
                {"query": q, "per_page": 15, "size": "large"}
            )
            req = urllib.request.Request(
                url,
                headers={"Authorization": api_key, "User-Agent": "AIDigestBot/1.0"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            photos = data.get("photos", [])
            if not photos:
                print(f"[image] Pexels: no results for '{q}'")
                continue

            # Deterministic daily rotation so the same query varies day to day.
            photo = photos[today.timetuple().tm_yday % len(photos)]
            src = photo.get("src", {})
            img_url = src.get("large2x") or src.get("large") or src.get("original")
            if not img_url:
                continue

            req2 = urllib.request.Request(img_url, headers={"User-Agent": "AIDigestBot/1.0"})
            with urllib.request.urlopen(req2, timeout=20) as resp:
                raw = resp.read()
            photographer = photo.get("photographer", "")
            print(f"[image] Pexels photo for '{q}' (by {photographer})")
            return Image.open(BytesIO(raw)).convert("RGB")
        except Exception as e:
            print(f"[image] Pexels fetch failed for '{q}': {e}")
            continue
    return None


def _cover_crop(img: Image.Image, w: int, h: int) -> Image.Image:
    """Scale + center-crop to exactly fill (w, h) — like CSS background-size: cover."""
    src_w, src_h = img.size
    scale = max(w / src_w, h / src_h)
    new_w, new_h = max(w, int(src_w * scale + 0.5)), max(h, int(src_h * scale + 0.5))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - w) // 2
    top = (new_h - h) // 2
    return img.crop((left, top, left + w, top + h))


def _readability_overlay(accent: tuple) -> Image.Image:
    """Dark gradient: subtle at top (for the brand line), heavy at the bottom
    (for the teaser). Returns an RGBA layer to composite over the photo."""
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    px = overlay.load()
    top_dark_until = 230
    bottom_start = int(HEIGHT * 0.40)
    for y in range(HEIGHT):
        a = 0
        if y < top_dark_until:
            a = int(150 * (1 - y / top_dark_until))
        if y >= bottom_start:
            t = (y - bottom_start) / (HEIGHT - bottom_start)
            a = max(a, int(20 + 215 * (t ** 1.3)))
        if a:
            for x in range(WIDTH):
                px[x, y] = (4, 6, 14, a)
    return overlay


def _generate_photo_card(
    teaser: str,
    image_query: str,
    main_source: str,
    username: str,
    today: date,
    output_filename: str,
) -> Path | None:
    photo = _fetch_pexels_photo(image_query, today)
    if photo is None:
        return None

    theme = THEMES[today.weekday()]
    accent = theme["accent"]
    dim = theme["dim"]

    img = _cover_crop(photo, WIDTH, HEIGHT)
    img = Image.alpha_composite(img.convert("RGBA"), _readability_overlay(accent)).convert("RGB")
    draw = ImageDraw.Draw(img)

    # ── Top brand line ─────────────────────────────────────────────
    draw.rectangle([(60, 64), (60 + 56, 70)], fill=accent)
    font_brand = _load_font(30, bold=True)
    _draw_text_shadow(draw, (60, 82), "IA DIÁRIO", font_brand, TEXT_WHITE, offset=2)

    font_date = _load_font(24)
    date_str = today.strftime("%d %b %Y").upper()
    dw = _text_w(draw, date_str, font_date)
    _draw_text_shadow(draw, (WIDTH - 60 - dw, 86), date_str, font_date, TEXT_GRAY, offset=2)

    # ── Bottom teaser (the hook) ───────────────────────────────────
    teaser = (teaser or "").strip().strip('"').strip()
    if not teaser:
        teaser = "Novidades de IA que você precisa ver"

    font_teaser = _load_font(72, bold=True)
    wrapped = textwrap.fill(teaser, width=20).split("\n")[:3]
    line_gap = 14
    line_hs = [_text_h(draw, ln, font_teaser) for ln in wrapped]
    block_h = sum(line_hs) + line_gap * (len(wrapped) - 1)

    username_y = HEIGHT - 88
    kicker_gap = 34
    start_y = username_y - 40 - block_h

    # Accent kicker bar above the teaser
    draw.rectangle([(60, start_y - kicker_gap), (60 + 80, start_y - kicker_gap + 7)], fill=accent)

    y = start_y
    for ln, lh in zip(wrapped, line_hs):
        _draw_text_shadow(draw, (60, y), ln, font_teaser, TEXT_WHITE, offset=3)
        y += lh + line_gap

    # ── Footer: handle + source ────────────────────────────────────
    font_wm = _load_font(28, bold=True)
    _draw_text_shadow(draw, (60, username_y), username, font_wm, dim, offset=2)

    if main_source:
        font_src = _load_font(22, bold=True)
        label = f"via {main_source}".upper()
        lw = _text_w(draw, label, font_src)
        _draw_text_shadow(draw, (WIDTH - 60 - lw, username_y + 4), label, font_src, TEXT_GRAY, offset=2)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / output_filename
    img.save(str(out_path), "JPEG", quality=90)
    print(f"[image] Photo card saved → {out_path}")
    return out_path


# ── Legacy fallback: text-on-gradient card ───────────────────────────────────
def _vertical_gradient(draw: ImageDraw.ImageDraw, top: tuple, bottom: tuple):
    for y in range(HEIGHT):
        t = y / HEIGHT
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))


def _draw_badge(draw, text, x, y, font, color) -> int:
    tw = _text_w(draw, text, font)
    th = _text_h(draw, text, font)
    px, py = 14, 6
    draw.rectangle([x, y, x + tw + px * 2, y + th + py * 2], fill=color)
    draw.text((x + px, y + py), text, font=font, fill=TEXT_WHITE)
    return tw + px * 2


def _generate_text_card(headline, stories, username, today, output_filename) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    theme = THEMES[today.weekday()]
    accent = theme["accent"]
    dim = theme["dim"]

    img = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)
    _vertical_gradient(draw, BG_TOP, theme["bg_bottom"])

    for y in range(4, HEIGHT, 8):
        t = y / HEIGHT
        r = int(BG_TOP[0] + (theme["bg_bottom"][0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (theme["bg_bottom"][1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (theme["bg_bottom"][2] - BG_TOP[2]) * t)
        draw.line([(0, y), (WIDTH, y)], fill=(max(0, r - 5), max(0, g - 5), max(0, b - 5)))

    draw.rectangle([(60, 58), (WIDTH - 60, 63)], fill=accent)
    font_brand = _load_font(32, bold=True)
    draw.text((60, 76), "IA DIÁRIO", font=font_brand, fill=accent)

    font_date = _load_font(26)
    date_str = today.strftime("%d %b %Y").upper()
    dw = _text_w(draw, date_str, font_date)
    draw.text((WIDTH - 60 - dw, 80), date_str, font=font_date, fill=dim)

    font_headline = _load_font(54, bold=True)
    wrapped = textwrap.fill(headline[:110], width=22)
    lines = wrapped.split("\n")[:3]
    y = 195
    for line in lines:
        lw = _text_w(draw, line, font_headline)
        draw.text(((WIDTH - lw) // 2, y), line, font=font_headline, fill=TEXT_WHITE)
        y += _text_h(draw, line, font_headline) + 16

    main_source = stories[0].get("source", "") if stories else ""
    if main_source:
        font_badge = _load_font(22, bold=True)
        badge_color = SOURCE_COLORS.get(main_source.lower(), accent)
        badge_text = main_source.upper()
        bw = _text_w(draw, badge_text, font_badge) + 28
        bx = (WIDTH - bw) // 2
        _draw_badge(draw, badge_text, bx, y + 18, font_badge, badge_color)
        y += 62
    else:
        y += 30

    divider_y = max(y + 28, 530)
    draw.rectangle([(60, divider_y), (WIDTH - 60, divider_y + 2)], fill=accent)
    font_section = _load_font(20, bold=True)
    label = "TAMBÉM HOJE"
    lw = _text_w(draw, label, font_section)
    lx = (WIDTH - lw) // 2
    draw.rectangle([lx - 14, divider_y - 13, lx + lw + 14, divider_y + 15], fill=BG_TOP)
    draw.text((lx, divider_y - 10), label, font=font_section, fill=dim)

    secondary = stories[1:4] if len(stories) > 1 else []
    font_story = _load_font(30)
    font_src_sm = _load_font(19, bold=True)
    story_y = divider_y + 42
    for s in secondary:
        title = s.get("title", "")[:78]
        source = s.get("source", "")
        src_color = SOURCE_COLORS.get(source.lower(), dim)
        dot_cx, dot_cy = 72, story_y + 13
        draw.ellipse([dot_cx - 6, dot_cy - 6, dot_cx + 6, dot_cy + 6], fill=accent)
        _draw_badge(draw, source.upper(), 90, story_y, font_src_sm, src_color)
        wrapped_t = textwrap.fill(title, width=40).split("\n")[:2]
        ty = story_y + 34
        for tl in wrapped_t:
            draw.text((90, ty), tl, font=font_story, fill=TEXT_GRAY)
            ty += _text_h(draw, tl, font_story) + 7
        story_y += 118

    draw.rectangle([(60, HEIGHT - 82), (WIDTH - 60, HEIGHT - 78)], fill=accent)
    font_wm = _load_font(28, bold=True)
    wmw = _text_w(draw, username, font_wm)
    draw.text(((WIDTH - wmw) // 2, HEIGHT - 58), username, font=font_wm, fill=dim)

    out_path = OUTPUT_DIR / output_filename
    img.save(str(out_path), "JPEG", quality=92)
    print(f"[image] Fallback text card saved → {out_path}")
    return out_path


def generate_card(
    headline: str,
    stories: list[dict],
    teaser: str | None = None,
    image_query: str | None = None,
    username: str = "@danquiell",
    today: date | None = None,
    output_filename: str = "card.jpg",
) -> Path:
    """Try the photo-hero card first; fall back to the legacy text card."""
    if today is None:
        today = date.today()
    main_source = stories[0].get("source", "") if stories else ""

    try:
        path = _generate_photo_card(
            teaser=teaser or headline,
            image_query=image_query or PEXELS_FALLBACK_QUERY,
            main_source=main_source,
            username=username,
            today=today,
            output_filename=output_filename,
        )
        if path is not None:
            return path
    except Exception as e:
        print(f"[image] Photo card failed ({e}) — falling back to text card")

    return _generate_text_card(headline, stories, username, today, output_filename)


if __name__ == "__main__":
    path = generate_card(
        headline="OpenAI lança modelo que programa melhor que 99% dos humanos",
        stories=[
            {"title": "OpenAI lança modelo que programa melhor que 99% dos humanos", "source": "TechCrunch"},
            {"title": "Google anuncia Gemini 2.5 Ultra com raciocínio avançado", "source": "The Verge"},
            {"title": "Anthropic levanta US$3bi na maior rodada da história da IA", "source": "Bloomberg"},
        ],
        teaser="A IA que programa sozinha chegou",
        image_query="humanoid robot closeup",
        username="@danquiell",
    )
    print(f"Preview gerado: {path}")
