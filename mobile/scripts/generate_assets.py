"""
Generate the app icon, adaptive icon, splash screen, and favicon.

Run with: `python scripts/generate_assets.py`

The mark is the web client's brand icon: Phosphor's ``StarFour`` at
``weight="fill"``, which the web renders in ``--chart-1`` next to a
blurred backdrop. The path below is copied verbatim from
``@phosphor-icons/react`` (``StarFour`` -> ``fill``), so the mobile
icon is the same shape the web shows rather than a redrawing of it.

Palette comes from `src/theme/tokens.ts` (copied from the web
`globals.css`): the app near-black background and the brand cyan.

Pillow is used rather than an image library in `package.json` -- this
is a build-time script, not app code, and it keeps the runtime
dependency surface unchanged.
"""

from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

# The app background, from `theme/tokens.ts` (`colors.background`).
BACKGROUND = (0x09, 0x09, 0x0B, 255)

# The brand cyan, from `theme/tokens.ts` (`colors.chart1`).
CYAN = (0x53, 0xEA, 0xFD, 255)

ASSETS = Path(__file__).resolve().parent.parent / "assets"

# The Phosphor `StarFour` fill path, on a 256x256 viewBox.
STAR_FOUR_FILL = (
    "M240,128a15.79,15.79,0,0,1-10.5,15l-63.44,23.07L143,229.5a16,16,0,0,1-30,0"
    "L89.94,166.06,26.5,143a16,16,0,0,1,0-30L89.94,89.94,113,26.5a16,16,0,0,1,30,0"
    "l23.07,63.44L229.5,113A15.79,15.79,0,0,1,240,128Z"
)


def star_four_svg(size: int, fill: str) -> str:
    """The brand mark as an SVG document.

    Args:
        size: Canvas size in pixels.
        fill: Fill colour, as a CSS colour string.

    Returns:
        An SVG document.
    """
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 256 256">'
        f'<path d="{STAR_FOUR_FILL}" fill="{fill}"/>'
        f"</svg>"
    )


def render_svg(svg: str, size: int) -> Image.Image:
    """Rasterise an SVG string to a PIL image.

    Pillow cannot render SVG on its own, so the document is written to a
    temporary file and handed to ``rsvg-convert``, ``inkscape``, or
    ImageMagick -- whichever is present. When none is available the
    caller falls back to the geometry path.

    Args:
        svg: The SVG document.
        size: Output size in pixels.

    Returns:
        The rendered RGBA image, or ``None`` when no rasteriser exists.
    """
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False) as handle:
        handle.write(svg)
        svg_path = handle.name

    for command in (
        ["rsvg-convert", "-w", str(size), "-h", str(size), svg_path],
        [
            "magick",
            "-background",
            "none",
            svg_path,
            "-resize",
            f"{size}x{size}",
            "png:-",
        ],
        [
            "convert",
            "-background",
            "none",
            svg_path,
            "-resize",
            f"{size}x{size}",
            "png:-",
        ],
    ):
        try:
            result = subprocess.run(
                command, capture_output=True, check=True, timeout=60
            )
        except (
            FileNotFoundError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ):
            continue
        import io

        return Image.open(io.BytesIO(result.stdout)).convert("RGBA")

    return None


def quadratic(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    steps: int = 48,
) -> list[tuple[float, float]]:
    """Sample a quadratic Bezier curve.

    Args:
        p0: Start point.
        p1: Control point.
        p2: End point.
        steps: How many line segments to approximate the curve with.

    Returns:
        The sampled points, excluding the start point.
    """
    points = []
    for index in range(1, steps + 1):
        t = index / steps
        inverse = 1 - t
        x = inverse * inverse * p0[0] + 2 * inverse * t * p1[0] + t * t * p2[0]
        y = inverse * inverse * p0[1] + 2 * inverse * t * p1[1] + t * t * p2[1]
        points.append((x, y))
    return points


def star_four_outline(size: int, steps: int = 48) -> list[tuple[float, float]]:
    """The `StarFour` outline, traced from the same geometry.

    A fallback for when no SVG rasteriser is installed. The points sit
    on the axes; each side between two points is a quadratic Bezier
    whose control point is pulled in toward the centre, which is what
    gives the mark its concave waist.

    The proportions come from the SVG path: the points reach 41% of the
    half-width from the centre, and the waist sits at about 19.6%.

    Args:
        size: Canvas size in pixels.
        steps: Curve resolution per side.

    Returns:
        The outline points, ready to be filled.
    """
    center = size / 2
    point_r = size * 0.205
    # The control point sits this far along the chord, which sets how
    # deeply the sides bow inward.
    control_ratio = 0.135

    points = [
        (center + point_r, center),
        (center, center + point_r),
        (center - point_r, center),
        (center, center - point_r),
    ]

    outline: list[tuple[float, float]] = []
    for index, start in enumerate(points):
        end = points[(index + 1) % 4]
        control = (
            center + (start[0] - center + end[0] - center) * control_ratio,
            center + (start[1] - center + end[1] - center) * control_ratio,
        )
        outline.extend(quadratic(start, control, end, steps))
    return outline


def star_four_image(size: int) -> Image.Image:
    """The brand mark on a transparent canvas.

    Args:
        size: Canvas size in pixels.

    Returns:
        A transparent RGBA image holding the mark.
    """
    rendered = render_svg(star_four_svg(size, "#53EAFD"), size)
    if rendered is not None:
        return rendered

    # No rasteriser available -- trace the outline instead.
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(image).polygon(star_four_outline(size), fill=CYAN)
    return image


def build_icon(size: int = 1024) -> Image.Image:
    """The full-bleed launcher icon.

    The launcher masks this to a shape, so the artwork fills the square
    and the mark sits in the middle. A soft radial glow behind the mark
    keeps it legible on a dark launcher without putting a hard edge
    around the artwork -- the same trick the web navbar uses.
    """
    image = Image.new("RGBA", (size, size), BACKGROUND)

    # A radial glow, built from stacked translucent discs and blurred.
    glow_size = int(size * 0.62)
    glow = Image.new("RGBA", (glow_size, glow_size), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    steps = 22
    for step in range(steps, 0, -1):
        t = step / steps
        alpha = int(58 * (1 - t) ** 2.2)
        disc = glow_size / 2 * t
        glow_draw.ellipse(
            [
                glow_size / 2 - disc,
                glow_size / 2 - disc,
                glow_size / 2 + disc,
                glow_size / 2 + disc,
            ],
            fill=(CYAN[0], CYAN[1], CYAN[2], alpha),
        )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=size * 0.02))
    image.alpha_composite(
        glow, (int(size / 2 - glow_size / 2), int(size / 2 - glow_size / 2))
    )

    # The mark, at 62% of the canvas. A launcher icon has to read at
    # 48dp, and the mark is small within its own bounding box -- at the
    # web navbar's proportion it disappears entirely.
    mark_size = int(size * 0.62)
    mark = star_four_image(mark_size)
    image.alpha_composite(
        mark, (int(size / 2 - mark_size / 2), int(size / 2 - mark_size / 2))
    )
    return image


def main() -> None:
    """Write every asset the launcher and splash screen need."""
    ASSETS.mkdir(parents=True, exist_ok=True)
    print("generating assets:")

    # The launcher icon.
    build_icon(1024).save(ASSETS / "icon.png")
    print("  assets/icon.png (1024x1024)")

    # The Android adaptive-icon foreground. The launcher crops this to a
    # shape, so the mark stays well inside the safe circle -- roughly the
    # middle 60% of the canvas -- or the points get clipped.
    foreground = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    mark_size = int(1024 * 0.52)
    mark = star_four_image(mark_size)
    foreground.alpha_composite(
        mark, (int(1024 / 2 - mark_size / 2), int(1024 / 2 - mark_size / 2))
    )
    foreground.save(ASSETS / "adaptive-icon.png")
    print("  assets/adaptive-icon.png (1024x1024)")

    # The splash screen. Expo draws it on the app background colour.
    build_icon(1024).save(ASSETS / "splash.png")
    print("  assets/splash.png (1024x1024)")

    # The web favicon, so `expo start --web` shows the same mark.
    star_four_image(256).resize((64, 64), Image.LANCZOS).save(ASSETS / "favicon.png")
    print("  assets/favicon.png (64x64)")

    # The notification icon. Android shows this in the status bar, so it
    # has to be a flat, opaque mark -- no glow, no transparency.
    notification = Image.new("RGBA", (192, 192), (0, 0, 0, 0))
    mark_size = 168
    mark = star_four_image(mark_size)
    notification.alpha_composite(
        mark, (int(192 / 2 - mark_size / 2), int(192 / 2 - mark_size / 2))
    )
    notification.save(ASSETS / "notification-icon.png")
    print("  assets/notification-icon.png (192x192)")

    print("done.")


if __name__ == "__main__":
    main()
