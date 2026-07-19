"""生成复盘长图。"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    ImageFont = None  # type: ignore[assignment]

from review.renderer.html_renderer import HtmlRenderer


class ReviewImageRenderError(RuntimeError):
    """Raised when review image rendering cannot proceed."""


CANVAS_WIDTH = 1200
RENDER_SCALE = 2
BG = "#efe6d7"
PANEL = "#ffffff"
BORDER = "#ded1bf"
TEXT = "#2b2218"
ACCENT = "#b86a2f"
LEFT = 56
TOP = 48
LINE_GAP = 12
SECTION_GAP = 30


def render_review_image(payload: dict[str, Any], output_dir: Path, trade_day: date) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"review_{trade_day.isoformat()}.png"
    _render_png(payload, output_path, trade_day)
    return output_path


def _render_png(payload: dict[str, Any], output_path: Path, trade_day: date) -> None:
    _ensure_pillow_available()
    scale = RENDER_SCALE
    width = CANVAS_WIDTH * scale
    height = 4200 * scale
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    fonts = _fonts(scale)

    visual = _visual_payload(payload, trade_day)

    y = TOP * scale
    y = _draw_header(draw, fonts, visual, y, scale)
    y = _draw_cards(draw, fonts, visual["cards"], y + 22 * scale, scale)
    for section in visual["sections"]:
        y = _draw_section(draw, fonts, section, y + SECTION_GAP * scale, scale)

    cropped = img.crop((0, 0, width, min(height, y + 80 * scale)))
    final = cropped.resize((cropped.width // scale, cropped.height // scale), Image.Resampling.LANCZOS)
    final.save(output_path, format="PNG")


def _visual_payload(payload: dict[str, Any], trade_day: date) -> dict[str, Any]:
    return ReviewNarrativeAdapter().build_visual_payload(payload, trade_day)


class ReviewNarrativeAdapter:
    def build_visual_payload(self, payload: dict[str, Any], trade_day: date) -> dict[str, Any]:
        from review.narrative import ReviewNarrative

        return ReviewNarrative().build_visual_payload(payload, trade_day)


def _ensure_pillow_available() -> None:
    if Image is None or ImageDraw is None or ImageFont is None:
        raise ReviewImageRenderError(
            "Pillow is required to render review images. Install project dependencies with `python3 -m pip install -e .[dev]`."
        )


def _fonts(scale: int) -> dict[str, Any]:
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
    ]

    def load(size: int):
        for path in candidates:
            p = Path(path)
            if p.exists():
                try:
                    return ImageFont.truetype(str(p), size=size * scale)
                except Exception:
                    pass
        return ImageFont.load_default()

    return {
        "title": load(28),
        "card_value": load(22),
        "section": load(18),
        "body": load(14),
        "small": load(12),
    }


def _draw_header(draw, fonts: dict[str, Any], visual: dict[str, Any], y: int, scale: int) -> int:
    width = CANVAS_WIDTH * scale
    header_h = 260 * scale
    x1 = LEFT * scale
    x2 = width - LEFT * scale
    radius = 28 * scale
    colors = ["#5e3218", "#8b471f", "#c77a35", "#e6a24b", "#f3cc7a"]
    band_h = max(1, header_h // len(colors))
    for idx, color in enumerate(colors):
        band_top = y + idx * band_h
        band_bottom = y + header_h if idx == len(colors) - 1 else band_top + band_h
        draw.rounded_rectangle((x1, band_top, x2, band_bottom), radius=radius if idx in (0, len(colors) - 1) else 0, fill=color)
    draw.rounded_rectangle((x1, y, x2, y + header_h), radius=radius, outline="#8b4b22", width=max(2, scale))
    draw.text((x1 + 26 * scale, y + 24 * scale), visual["header"]["title"], font=fonts["title"], fill="white")
    draw.text((x1 + 26 * scale, y + 80 * scale), visual["header"]["subtitle"], font=fonts["body"], fill="#f8f2ea")
    _draw_wrapped_text(draw, visual["header"]["summary"], fonts["body"], x1 + 26 * scale, y + 120 * scale, x2 - x1 - 52 * scale, "#f8f2ea", scale)
    return y + header_h


def _draw_cards(draw, fonts: dict[str, Any], cards: list[dict[str, Any]], top: int, scale: int) -> int:
    width = CANVAS_WIDTH * scale
    left = LEFT * scale
    gap = 18 * scale
    card_w = (width - left * 2 - gap) // 2
    card_h = 174 * scale
    for idx, card in enumerate(cards):
        row, col = divmod(idx, 2)
        x = left + col * (card_w + gap)
        y = top + row * (card_h + gap)
        draw.rounded_rectangle((x, y, x + card_w, y + card_h), radius=20 * scale, fill=PANEL, outline=BORDER, width=max(1, scale))
        draw.text((x + 22 * scale, y + 18 * scale), card["label"], font=fonts["section"], fill=ACCENT)
        value_bottom = _draw_wrapped_text(
            draw,
            card["value"],
            fonts["card_value"],
            x + 22 * scale,
            y + 56 * scale,
            card_w - 44 * scale,
            TEXT,
            scale,
        )
        _draw_wrapped_text(draw, card["note"], fonts["body"], x + 22 * scale, value_bottom + 8 * scale, card_w - 44 * scale, TEXT, scale)
    return top + 2 * card_h + gap


def _draw_section(draw, fonts: dict[str, Any], section: dict[str, Any], top: int, scale: int) -> int:
    width = CANVAS_WIDTH * scale
    left = LEFT * scale
    bar_h = 54 * scale
    box_w = width - left * 2
    draw.rounded_rectangle((left, top, left + 300 * scale, top + bar_h), radius=bar_h // 2, fill="#ead8bf")
    draw.text((left + 20 * scale, top + 12 * scale), f"{section['index']} · {section['title']}", font=fonts["section"], fill="#6f4c31")
    body_top = top + bar_h + 10 * scale
    body_lines = section["lines"]
    body_height = _measure_lines(draw, fonts["body"], body_lines, box_w - 44 * scale, scale)
    block_h = body_height + 34 * scale
    draw.rounded_rectangle((left, body_top, left + box_w, body_top + block_h), radius=20 * scale, fill=PANEL, outline=BORDER, width=max(1, scale))
    y = body_top + 18 * scale
    for line in body_lines:
        y = _draw_wrapped_text(draw, line, fonts["body"], left + 22 * scale, y, box_w - 44 * scale, TEXT, scale)
        y += 8 * scale
    return body_top + block_h


def _draw_wrapped_text(draw, text: str, font: Any, x: int, y: int, max_width: int, fill: str, scale: int) -> int:
    lines = _wrap_text(draw, text, font, max_width)
    line_height = _line_height(font, scale)
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y


def _measure_lines(draw, font: Any, lines: list[str], max_width: int, scale: int) -> int:
    total = 0
    line_height = _line_height(font, scale)
    for line in lines:
        total += len(_wrap_text(draw, line, font, max_width)) * line_height + LINE_GAP * scale
    return total


def _line_height(font: Any, scale: int) -> int:
    size = getattr(font, "size", 14 * scale)
    return size + 8 * scale


def _wrap_text(draw, text: str, font: Any, max_width: int) -> list[str]:
    chars = list(str(text))
    if not chars:
        return [""]
    lines: list[str] = []
    current = ""
    for ch in chars:
        candidate = current + ch
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines
