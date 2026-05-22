"""
Generates a 1080x1080 LinkedIn card using Pillow.
7 rotating color themes by weekday. Shows main headline + up to 3 secondary stories.
"""
import textwrap
from datetime import date
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUTPUT_DIR = Path(__file__).parent.parent / "output"
ASSETS_DIR = Path(__file__).parent.parent / "assets" / "fonts"

WIDTH, HEIGHT = 1080, 1080
BG_TOP = (8, 8, 16)

# One theme per weekday (Mon=0 … Sun=6)
THEMES = [
    {"accent": (29, 78, 216),   "bg_bottom": (12, 20, 42),  "dim": (90, 115, 175)},   # Mon — blue
    {"accent": (124, 58, 237),  "bg_bottom": (20, 12, 42),  "dim": (115, 90, 175)},   # Tue — purple
    {"accent": (5, 150, 105),   "bg_bottom": (8, 32, 22),   "dim": (70, 135, 100)},   # Wed — emerald
    {"accent": (217, 119, 6),   "bg_bottom": (32, 20, 6),   "dim": (155, 120, 65)},   # Thu — amber
    {"accent": (6, 182, 212),   "bg_bottom": (6, 30, 38),   "dim": (65, 145, 165)},   # Fri — cyan
    {"accent": (225, 29, 72),   "bg_bottom": (36, 6, 16),   "dim": (155, 70, 90)},    # Sat — rose
    {"accent": (99, 102, 241),  "bg_bottom": (16, 14, 44),  "dim": (105, 105, 180)},  # Sun — indigo
]

TEXT_WHITE = (255, 255, 255)
TEXT_GRAY = (195, 195, 210)

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


def _vertical_gradient(draw: ImageDraw.ImageDraw, top: tuple, bottom: tuple):
    for y in range(HEIGHT):
        t = y / HEIGHT
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))


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


def _draw_badge(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, font, color: tuple) -> int:
    """Draw a filled label badge. Returns total badge width."""
    tw = _text_w(draw, text, font)
    th = _text_h(draw, text, font)
    px, py = 14, 6
    draw.rectangle([x, y, x + tw + px * 2, y + th + py * 2], fill=color)
    draw.text((x + px, y + py), text, font=font, fill=TEXT_WHITE)
    return tw + px * 2


def generate_card(
    headline: str,
    stories: list[dict],
    username: str = "@daniel",
    today: date | None = None,
    output_filename: str = "card.jpg",
) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if today is None:
        today = date.today()

    theme = THEMES[today.weekday()]
    accent = theme["accent"]
    dim = theme["dim"]

    img = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)

    # Background gradient
    _vertical_gradient(draw, BG_TOP, theme["bg_bottom"])

    # Subtle scanline texture (every 8px)
    for y in range(4, HEIGHT, 8):
        t = y / HEIGHT
        r = int(BG_TOP[0] + (theme["bg_bottom"][0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (theme["bg_bottom"][1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (theme["bg_bottom"][2] - BG_TOP[2]) * t)
        draw.line([(0, y), (WIDTH, y)], fill=(max(0, r - 5), max(0, g - 5), max(0, b - 5)))

    # ── Top accent bar ─────────────────────────────────────────────
    draw.rectangle([(60, 58), (WIDTH - 60, 63)], fill=accent)

    # Brand label
    font_brand = _load_font(32, bold=True)
    draw.text((60, 76), "IA DIÁRIO", font=font_brand, fill=accent)

    # Date (right-aligned)
    font_date = _load_font(26)
    date_str = today.strftime("%d %b %Y").upper()
    dw = _text_w(draw, date_str, font_date)
    draw.text((WIDTH - 60 - dw, 80), date_str, font=font_date, fill=dim)

    # ── Main headline ──────────────────────────────────────────────
    font_headline = _load_font(54, bold=True)
    wrapped = textwrap.fill(headline[:110], width=22)
    lines = wrapped.split("\n")[:3]
    y = 195
    for line in lines:
        lw = _text_w(draw, line, font_headline)
        draw.text(((WIDTH - lw) // 2, y), line, font=font_headline, fill=TEXT_WHITE)
        y += _text_h(draw, line, font_headline) + 16

    # Main source badge centered below headline
    main_source = stories[0].get("source", "") if stories else ""
    if main_source:
        font_badge = _load_font(22, bold=True)
        src_key = main_source.lower()
        badge_color = SOURCE_COLORS.get(src_key, accent)
        badge_text = main_source.upper()
        bw = _text_w(draw, badge_text, font_badge) + 28
        bx = (WIDTH - bw) // 2
        _draw_badge(draw, badge_text, bx, y + 18, font_badge, badge_color)
        y += 62
    else:
        y += 30

    # ── Divider with section label ─────────────────────────────────
    divider_y = max(y + 28, 530)
    draw.rectangle([(60, divider_y), (WIDTH - 60, divider_y + 2)], fill=accent)

    font_section = _load_font(20, bold=True)
    label = "TAMBÉM HOJE"
    lw = _text_w(draw, label, font_section)
    lx = (WIDTH - lw) // 2
    draw.rectangle([lx - 14, divider_y - 13, lx + lw + 14, divider_y + 15], fill=BG_TOP)
    draw.text((lx, divider_y - 10), label, font=font_section, fill=dim)

    # ── Secondary stories ──────────────────────────────────────────
    secondary = stories[1:4] if len(stories) > 1 else []
    font_story = _load_font(30)
    font_src_sm = _load_font(19, bold=True)

    story_y = divider_y + 42
    for s in secondary:
        title = s.get("title", "")[:78]
        source = s.get("source", "")
        src_key = source.lower()
        src_color = SOURCE_COLORS.get(src_key, dim)

        # Accent dot
        dot_cx, dot_cy = 72, story_y + 13
        draw.ellipse([dot_cx - 6, dot_cy - 6, dot_cx + 6, dot_cy + 6], fill=accent)

        # Source badge
        _draw_badge(draw, source.upper(), 90, story_y, font_src_sm, src_color)

        # Story title (up to 2 lines)
        wrapped_t = textwrap.fill(title, width=40)
        t_lines = wrapped_t.split("\n")[:2]
        ty = story_y + 34
        for tl in t_lines:
            draw.text((90, ty), tl, font=font_story, fill=TEXT_GRAY)
            ty += _text_h(draw, tl, font_story) + 7
        story_y += 118

    # ── Bottom accent bar ──────────────────────────────────────────
    draw.rectangle([(60, HEIGHT - 82), (WIDTH - 60, HEIGHT - 78)], fill=accent)

    # Username
    font_wm = _load_font(28, bold=True)
    wmw = _text_w(draw, username, font_wm)
    draw.text(((WIDTH - wmw) // 2, HEIGHT - 58), username, font=font_wm, fill=dim)

    out_path = OUTPUT_DIR / output_filename
    img.save(str(out_path), "JPEG", quality=92)
    print(f"[image] Card saved → {out_path}")
    return out_path


if __name__ == "__main__":
    path = generate_card(
        headline="OpenAI lança modelo que programa melhor que 99% dos humanos",
        stories=[
            {"title": "OpenAI lança modelo que programa melhor que 99% dos humanos", "source": "TechCrunch"},
            {"title": "Google anuncia Gemini 2.5 Ultra com raciocínio avançado", "source": "The Verge"},
            {"title": "Anthropic levanta US$3bi na maior rodada da história da IA", "source": "Bloomberg"},
            {"title": "Meta lança Llama 4 com 1 trilhão de parâmetros open-source", "source": "Hacker News"},
        ],
        username="@danquiell",
    )
    print(f"Preview gerado: {path}")
