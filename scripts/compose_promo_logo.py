#!/usr/bin/env python3
"""Compose the existing Topos Calibrator icon into a README wordmark.

The project icon is kept unchanged. This deterministic compositor only adds
the exact brand text locally so that the spelling stays correct in the GitHub
asset.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MARK_PATH = PROJECT_ROOT / "resources" / "app-icons" / "topos-calibrator.png"
OUTPUT_PATH = PROJECT_ROOT / "resources" / "app-icons" / "topos-calibrator-logo.png"

WIDTH, HEIGHT = 2170, 725


def load_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = (
        ("/System/Library/Fonts/HelveticaNeue.ttc", 1),
        ("/System/Library/Fonts/Helvetica.ttc", 1),
        ("/System/Library/Fonts/Supplemental/Verdana Bold.ttf", 0),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
    )
    for path, index in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size, index=index)
    return ImageFont.load_default()


def lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def spectral_color(position: float) -> tuple[int, int, int]:
    stops = (
        (0.00, (0, 220, 210)),
        (0.28, (20, 95, 255)),
        (0.52, (90, 35, 225)),
        (0.72, (255, 15, 130)),
        (0.88, (255, 65, 40)),
        (1.00, (255, 185, 35)),
    )
    for (left, color_left), (right, color_right) in zip(stops, stops[1:]):
        if position <= right:
            return lerp(color_left, color_right, (position - left) / (right - left))
    return stops[-1][1]


def main() -> None:
    if not MARK_PATH.is_file():
        raise SystemExit(f"Icon source not found: {MARK_PATH}")

    # Fully transparent canvas: only the supplied icon, its soft shadow, and
    # the exact wordmark will contribute visible pixels.
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))

    # Soft shadow under the mark.
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle((45, 80, 605, 640), radius=108, fill=(8, 16, 48, 105))
    shadow = shadow.filter(ImageFilter.GaussianBlur(28))
    canvas.alpha_composite(shadow)

    with Image.open(MARK_PATH) as mark_source:
        mark = mark_source.convert("RGBA")
        mark.thumbnail((560, 560), Image.Resampling.LANCZOS)
    canvas.alpha_composite(mark, (45, 80))

    # Add only the requested wordmark on the right of the supplied icon.
    wordmark = "Topos Calibrator"
    font = load_font(190)
    mask = Image.new("L", canvas.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text((620, 205), wordmark, font=font, fill=255, stroke_width=1)
    # Paint the wordmark with the same cool-to-warm color language as the icon.
    text_gradient = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    gradient_draw = ImageDraw.Draw(text_gradient)
    for x in range(620, WIDTH):
        color = spectral_color((x - 620) / (WIDTH - 620))
        gradient_draw.line((x, 230, x, 560), fill=(*color, 255))
    canvas = Image.composite(text_gradient, canvas, mask)

    canvas.save(OUTPUT_PATH, format="PNG", optimize=True)
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
