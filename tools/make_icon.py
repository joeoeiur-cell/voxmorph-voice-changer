"""Generate assets/voxmorph.ico procedurally.

Keeps the repo binary-free and guarantees CI always has an icon: a cyan
waveform mark on a dark rounded square, rendered at every size Windows asks
for (16 -> 256 px).
"""
from __future__ import annotations

import math
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise SystemExit("Pillow is required: pip install pillow")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "voxmorph.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)

BG = (14, 17, 22, 255)
ACCENT = (34, 211, 238, 255)
ACCENT_DIM = (14, 116, 144, 255)


def render(size: int) -> "Image.Image":
    ss = 4  # supersample for clean edges
    s = size * ss
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=BG)

    # symmetric waveform bars, tallest in the middle
    bars = 7
    margin = s * 0.20
    usable = s - 2 * margin
    bw = usable / (bars * 2 - 1)
    cy = s / 2
    for i in range(bars):
        rel = abs(i - (bars - 1) / 2) / ((bars - 1) / 2)
        h = (s * 0.30) * (1.0 - 0.62 * rel ** 1.5) + s * 0.055
        x = margin + i * bw * 2
        color = ACCENT if rel < 0.7 else ACCENT_DIM
        d.rounded_rectangle(
            [x, cy - h, x + bw, cy + h],
            radius=max(1, int(bw * 0.45)),
            fill=color,
        )
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames = [render(n) for n in SIZES]
    frames[-1].save(OUT, format="ICO", sizes=[(n, n) for n in SIZES])
    png = OUT.with_suffix(".png")
    frames[-1].save(png, format="PNG")
    print(f"Wrote {OUT} and {png}")


if __name__ == "__main__":
    main()
