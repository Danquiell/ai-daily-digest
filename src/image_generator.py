"""
Generates a 1080x1080 Instagram card image using Pillow.
Dark gradient background, main headline, sub-headline, date, and watermark.
No external font dependency — falls back to Pillow's built-in font gracefully.
"""
import textwrap
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUTPUT_DIR = Path(__file__).parent.parent / "output"
ASSETS_DIR = Path(__file__).parent.parent / "assets" / "fonts"

# Card dimensions
WIDTH, HEIGHT = 1080, 1080

# Colors
BG_TOP = (13, 13, 13)        # #0D0D0D
BG_BOTTOM = (26, 26, 46)     # #1A1A2E
ACCENT = (99, 179, 237)      # #63B3ED — soft blue accent line
TEXT_WHITE = (255, 255, 255)
TEXT_GRAY = (180, 180, 190)
TEXT_DIM = (120, 120, 135)
WATERMARK_COLOR = (80, 80, 95)


def _vertical_gradient(draw: ImageDraw.ImageDraw, top: tuple, bottom: tuple):
    for y in range(HEIGHT):
        r = int(top[0] + (bottom[0] - top[0]) * y / HEIGHT)
        g = int(top[1] + (bottom[1] - top[1]) * y / HEIGHT)
        b = int(top[2] + (bottom[2] - top[2]) * y / HEIGHT)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates = [
            ASSETS_DIR / "Inter-Bold.ttf",
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
            Path("/System/Library/Fonts/Helvetica.ttc"),
        ]
    else:
        candidates = [
            ASSETS_DIR / "Inter-Regular.ttf",
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
            Path("/System/Library/Fonts/Helvetica.ttc"),
        ]

    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except Exception:
                continue

    return ImageFont.load_default()


def _draw_multiline_centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    y: int,
    max_width: int,
    color: tuple,
    line_spacing: int = 12,
) -> int:
    """Draw centered multi-line text, return the final y position."""
    wrapped = textwrap.fill(text, width=28)
    lines = wrapped.split("\n")
    total_height = 0
    line_heights = []

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        lh = bbox[3] - bbox[1]
        line_heights.append(lh)
        total_height += lh + line_spacing

    current_y = y
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        lw = bbox[2] - bbox[0]
        x = (WIDTH - lw) // 2
        draw.text((x, current_y), line, font=font, fill=color)
        current_y += line_heights[i] + line_spacing

    return current_y


def generate_card(
    headline: str,
    sub_headline: str = "",
    username: str = "@daniel",
    today: date | None = None,
    source: str = "",
    output_filename: str = "instagram_card.jpg",
) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if today is None:
        today = date.today()

    img = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)

    # Background gradient
    _vertical_gradient(draw, BG_TOP, BG_BOTTOM)

    # Subtle noise texture effect (thin horizontal lines)
    for y in range(0, HEIGHT, 4):
        alpha = 8
        r = max(0, BG_TOP[0] - alpha) if y % 8 == 0 else BG_TOP[0]
        draw.line([(0, y), (WIDTH, y)], fill=(r, r, r + 5), width=1)

    # Top accent bar
    draw.rectangle([(80, 80), (WIDTH - 80, 84)], fill=ACCENT)

    # Date top-right
    font_date = _load_font(28)
    date_str = today.strftime("%d %b %Y").upper()
    draw.text((WIDTH - 80, 100), date_str, font=font_date, fill=TEXT_DIM, anchor="ra" if hasattr(font_date, "getbbox") else None)

    # "IA DAILY" label
    font_label = _load_font(32, bold=True)
    draw.text((80, 95), "IA DIÁRIO", font=font_label, fill=ACCENT)

    # Main headline (large, centered, ~middle of card)
    font_headline = _load_font(62, bold=True)
    headline_clean = headline[:120]
    _draw_multiline_centered(draw, headline_clean, font_headline, y=340, max_width=920, color=TEXT_WHITE)

    # Accent divider
    draw.rectangle([(WIDTH // 2 - 60, 720), (WIDTH // 2 + 60, 724)], fill=ACCENT)

    # Sub-headline
    if sub_headline:
        font_sub = _load_font(34)
        _draw_multiline_centered(draw, sub_headline[:100], font_sub, y=745, max_width=860, color=TEXT_GRAY)

    # Source attribution
    if source:
        font_source = _load_font(26)
        src_text = f"via {source}"
        bbox = draw.textbbox((0, 0), src_text, font=font_source)
        sw = bbox[2] - bbox[0]
        draw.text(((WIDTH - sw) // 2, 910), src_text, font=font_source, fill=TEXT_DIM)

    # Bottom accent bar
    draw.rectangle([(80, HEIGHT - 84), (WIDTH - 80, HEIGHT - 80)], fill=ACCENT)

    # Watermark / username
    font_watermark = _load_font(30, bold=True)
    draw.text((WIDTH // 2, HEIGHT - 50), username, font=font_watermark, fill=WATERMARK_COLOR, anchor="ms" if hasattr(font_watermark, "getbbox") else None)

    out_path = OUTPUT_DIR / output_filename
    img.save(str(out_path), "JPEG", quality=92)
    print(f"[image] Card saved → {out_path}")
    return out_path


if __name__ == "__main__":
    path = generate_card(
        headline="OpenAI lança modelo que programa melhor que 99% dos humanos",
        sub_headline="GPT-5 Codex bate benchmarks históricos em competições de código",
        username="@daniel.rios",
        source="TechCrunch",
    )
    print(f"Preview gerado: {path}")
