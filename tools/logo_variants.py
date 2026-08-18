#!/usr/bin/env python3
"""Simp logo variants — round 2 (превью, не app icon).

Палитра globals.css (НЕ Mimolet purple):
  #0a0b0f фон · #ff2d6f акцент · #d61e5a deep · #fafbfc глиф
  опц. #d4a72c / #d8d8dc

Векторные силуэты (SVG) → rsvg-convert (точный AA) → squircle PNG.

Запуск:
    python3 tools/logo_variants.py
"""

from __future__ import annotations

import argparse
import math
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

BG = "#0a0b0f"
BG_RIM = "#13141a"
ACCENT = "#ff2d6f"
DEEP = "#d61e5a"
GLYPH = "#fafbfc"
GOLD = "#d4a72c"
GRAPHITE = "#d8d8dc"

SIZE = 512
MARK_VIEW = 512  # SVG viewBox
RSVG = "/opt/homebrew/bin/rsvg-convert"


def _svg_doc(body: str, view: int = MARK_VIEW) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{view}" height="{view}"
     viewBox="0 0 {view} {view}">
  <defs>
    <linearGradient id="g" x1="18%" y1="8%" x2="82%" y2="92%">
      <stop offset="0%" stop-color="{DEEP}"/>
      <stop offset="100%" stop-color="{ACCENT}"/>
    </linearGradient>
  </defs>
  {body}
</svg>
"""


def _rsvg(svg: str, px: int) -> Image.Image:
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
        f.write(svg.encode("utf-8"))
        svg_path = Path(f.name)
    png_path = svg_path.with_suffix(".png")
    try:
        subprocess.run(
            [RSVG, "-w", str(px), "-h", str(px), str(svg_path), "-o", str(png_path)],
            check=True,
            capture_output=True,
        )
        return Image.open(png_path).convert("RGBA")
    finally:
        svg_path.unlink(missing_ok=True)
        png_path.unlink(missing_ok=True)


def _squircle_base(size: int) -> Image.Image:
    """Тёмный squircle на прозрачном — с мягким rim."""
    hi = size * 2
    canvas = Image.new("RGBA", (hi, hi), (0, 0, 0, 0))
    m = Image.new("L", (hi, hi), 0)
    d = ImageDraw.Draw(m)
    pad = int(hi * 0.02)
    d.rounded_rectangle(
        [pad, pad, hi - 1 - pad, hi - 1 - pad],
        radius=int(hi * 0.235),
        fill=255,
    )
    m = m.filter(ImageFilter.GaussianBlur(1.2))
    rim = Image.new("RGBA", (hi, hi), (*tuple(int(BG_RIM[i : i + 2], 16) for i in (1, 3, 5)), 255))
    rim.putalpha(m)
    canvas.alpha_composite(rim)

    m2 = Image.new("L", (hi, hi), 0)
    d2 = ImageDraw.Draw(m2)
    pad2 = int(hi * 0.05)
    d2.rounded_rectangle(
        [pad2, pad2, hi - 1 - pad2, hi - 1 - pad2],
        radius=int(hi * 0.205),
        fill=255,
    )
    m2 = m2.filter(ImageFilter.GaussianBlur(1.0))
    core = Image.new("RGBA", (hi, hi), (*tuple(int(BG[i : i + 2], 16) for i in (1, 3, 5)), 255))
    core.putalpha(m2)
    canvas.alpha_composite(core)
    return canvas.resize((size, size), Image.LANCZOS)


def _compose(mark: Image.Image, size: int = SIZE) -> Image.Image:
    base = _squircle_base(size)
    box = int(size * 0.58)
    mark_r = mark.resize((box, box), Image.LANCZOS)
    x = (size - box) // 2
    y = (size - box) // 2
    base.alpha_composite(mark_r, (x, y))
    return base


# ── SVG marks (один герой-силуэт) ──────────────────────────────


def svg_r01_wave() -> str:
    """Волна — гребень встречи."""
    return _svg_doc(
        f"""
  <path fill="url(#g)" d="
    M 40 300
    C 90 90, 180 100, 250 235
    C 300 340, 380 130, 472 180
    C 450 390, 180 450, 40 300
    Z"/>
  <path fill="none" stroke="{GLYPH}" stroke-width="28" stroke-linecap="round"
        d="M 140 210 C 190 155, 270 275, 360 195"/>
"""
    )


def svg_r02_chevron() -> str:
    """Шеврон-узел с талией."""
    return _svg_doc(
        f"""
  <path fill="url(#g)" d="
    M 256 48
    C 280 48, 420 180, 420 210
    C 420 225, 360 245, 320 256
    C 360 267, 420 287, 420 302
    C 420 332, 280 464, 256 464
    C 232 464, 92 332, 92 302
    C 92 287, 152 267, 192 256
    C 152 245, 92 225, 92 210
    C 92 180, 232 48, 256 48
    Z"/>
  <path fill="{GLYPH}" d="
    M 256 190
    L 300 256
    L 256 322
    L 212 256
    Z"/>
"""
    )


def svg_r03_infinity() -> str:
    """Сплошная ∞ (заливка, не обводка с щелями)."""
    # Bernoulli lemniscate as filled thick ribbon via stroke on path
    return _svg_doc(
        f"""
  <path fill="none" stroke="url(#g)" stroke-width="58" stroke-linecap="round"
        stroke-linejoin="round"
        d="M 256 256
           C 256 190, 200 130, 150 130
           C 90 130, 70 200, 110 256
           C 70 312, 90 382, 150 382
           C 200 382, 256 322, 256 256
           C 256 322, 312 382, 362 382
           C 422 382, 442 312, 402 256
           C 442 200, 422 130, 362 130
           C 312 130, 256 190, 256 256"/>
  <circle cx="256" cy="256" r="22" fill="{GLYPH}"/>
"""
    )


def svg_r04_keyhole() -> str:
    """Ключ — unlock (единый силуэт, без щели шеи)."""
    return _svg_doc(
        f"""
  <path fill="url(#g)" d="
    M 256 64
    C 318 64, 368 114, 368 176
    C 368 220, 342 258, 308 278
    L 330 420
    C 334 448, 312 456, 288 456
    L 224 456
    C 200 456, 178 448, 182 420
    L 204 278
    C 170 258, 144 220, 144 176
    C 144 114, 194 64, 256 64
    Z"/>
  <circle cx="256" cy="176" r="46" fill="{GLYPH}"/>
  <rect x="236" y="208" width="40" height="190" rx="20" fill="{GLYPH}"/>
"""
    )


def svg_r05_link() -> str:
    """Звено — связь без Венн."""
    return _svg_doc(
        f"""
  <g transform="translate(256 256) rotate(28)">
    <ellipse cx="0" cy="0" rx="118" ry="175" fill="none"
             stroke="url(#g)" stroke-width="56"/>
  </g>
  <circle cx="256" cy="256" r="28" fill="{GLYPH}"/>
"""
    )


def svg_r06_spiral() -> str:
    """Спираль к ядру."""
    # Archimedean spiral path
    pts = []
    for i in range(220):
        t = 0.6 + (i / 219) * 2.0 * math.tau
        r = 28 + (i / 219) * 170
        x = 256 + r * math.cos(t)
        y = 256 + r * math.sin(t)
        pts.append(f"{'M' if i == 0 else 'L'} {x:.1f} {y:.1f}")
    d = " ".join(pts)
    return _svg_doc(
        f"""
  <path d="{d}" fill="none" stroke="url(#g)" stroke-width="46"
        stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="256" cy="256" r="32" fill="{GLYPH}"/>
"""
    )


def svg_r07_cassini() -> str:
    """Овал Кассини — две души / одна форма (не Венн)."""
    a, b = 78.0, 98.0
    pts = []
    for i in range(360):
        th = (i / 360) * math.tau
        disc = b**4 - (a**4) * (math.sin(2 * th) ** 2)
        if disc < 0:
            continue
        r2 = a * a * math.cos(2 * th) + math.sqrt(disc)
        if r2 <= 0:
            continue
        r = math.sqrt(r2) * 1.55
        x = 256 + r * math.cos(th)
        y = 256 + r * math.sin(th) * 0.92
        pts.append(f"{'M' if not pts else 'L'} {x:.1f} {y:.1f}")
    d = " ".join(pts) + " Z"
    return _svg_doc(
        f"""
  <path fill="url(#g)" d="{d}"/>
  <circle cx="256" cy="256" r="22" fill="{GLYPH}"/>
"""
    )


def svg_r08_comet() -> str:
    """Комета — толстый импульс сближения."""
    return _svg_doc(
        f"""
  <path fill="url(#g)" d="
    M 48 380
    C 120 355, 200 300, 280 230
    C 330 185, 370 145, 400 128
    C 455 95, 490 160, 450 210
    C 410 270, 340 320, 270 365
    C 180 420, 100 430, 48 380
    Z"/>
  <circle cx="400" cy="168" r="92" fill="url(#g)"/>
  <circle cx="400" cy="168" r="34" fill="{GLYPH}"/>
"""
    )


def svg_r09_knot() -> str:
    """Узел — переплетённая петля (один силуэт)."""
    return _svg_doc(
        f"""
  <path fill="none" stroke="url(#g)" stroke-width="54"
        stroke-linecap="round" stroke-linejoin="round"
        d="M 160 200
           C 160 120, 352 120, 352 200
           C 352 260, 280 280, 256 310
           C 232 280, 160 260, 160 200
           M 160 312
           C 160 392, 352 392, 352 312
           C 352 252, 280 232, 256 202
           C 232 232, 160 252, 160 312"/>
  <circle cx="256" cy="256" r="24" fill="{GLYPH}"/>
"""
    )


def svg_r10_pulse() -> str:
    """Пульс мэтча — одна толстая линия-знак."""
    return _svg_doc(
        f"""
  <path fill="none" stroke="url(#g)" stroke-width="52"
        stroke-linecap="round" stroke-linejoin="round"
        d="M 48 270
           L 140 270
           L 175 160
           L 230 360
           L 290 120
           L 340 270
           L 464 270"/>
  <circle cx="290" cy="120" r="22" fill="{GOLD}"/>
"""
    )


def svg_r11_embrace() -> str:
    """Объятие — две дуги слиты в один C-кольцевой силуэт."""
    return _svg_doc(
        f"""
  <path fill="none" stroke="url(#g)" stroke-width="58"
        stroke-linecap="round"
        d="M 170 140
           C 90 200, 90 340, 170 400
           C 210 430, 250 430, 256 400
           C 262 430, 302 430, 342 400
           C 422 340, 422 200, 342 140"/>
  <circle cx="256" cy="290" r="26" fill="{GLYPH}"/>
"""
    )


def svg_r12_ribbon() -> str:
    """Лента-бант — один непрерывный бант (не три фигуры)."""
    return _svg_doc(
        f"""
  <path fill="url(#g)" d="
    M 256 230
    C 200 140, 90 150, 90 230
    C 90 290, 180 310, 256 360
    C 332 310, 422 290, 422 230
    C 422 150, 312 140, 256 230
    Z
    M 256 250
    C 230 300, 210 340, 200 420
    L 256 380
    L 312 420
    C 302 340, 282 300, 256 250
    Z"/>
  <circle cx="256" cy="248" r="24" fill="{GLYPH}"/>
"""
    )


# Все кандидаты; SHOW_CODES — финальный глазной отбор
CANDIDATES: list[tuple[str, str, callable]] = [
    ("r01", "Волна", svg_r01_wave),
    ("r02", "Шеврон", svg_r02_chevron),
    ("r03", "Лента ∞", svg_r03_infinity),
    ("r04", "Ключ", svg_r04_keyhole),
    ("r05", "Звено", svg_r05_link),
    ("r06", "Спираль", svg_r06_spiral),
    ("r07", "Кассини", svg_r07_cassini),
    ("r08", "Комета", svg_r08_comet),
    ("r09", "Узел", svg_r09_knot),
    ("r10", "Пульс", svg_r10_pulse),
    ("r11", "Объятие", svg_r11_embrace),
    ("r12", "Бант", svg_r12_ribbon),
]

# Финал после глазного QA — слабые (пульс/объятие/бант) не экспортируем
SHOW_CODES: set[str] | None = {
    "r01",  # Волна
    "r02",  # Шеврон
    "r03",  # Лента ∞
    "r04",  # Ключ
    "r05",  # Звено
    "r06",  # Спираль
    "r07",  # Кассини
    "r08",  # Комета
    "r09",  # Узел
}


def render_one(svg_fn, size: int = SIZE) -> Image.Image:
    mark = _rsvg(svg_fn(), px=size * 2)
    return _compose(mark, size)


def main() -> None:
    ap = argparse.ArgumentParser(description="Simp logo variants round 2 (SVG)")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--size", type=int, default=SIZE)
    ap.add_argument("--only", type=str, default=None)
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    outs = (
        [args.out]
        if args.out
        else [
            Path("/tmp/simp-logo-variants"),
            root / "web" / "public" / "logo-variants" / "round2",
        ]
    )

    selected = CANDIDATES
    if args.only:
        want = {x.strip() for x in args.only.split(",")}
        selected = [c for c in CANDIDATES if c[0] in want]
    elif SHOW_CODES is not None:
        selected = [c for c in CANDIDATES if c[0] in SHOW_CODES]

    for out in outs:
        out.mkdir(parents=True, exist_ok=True)
        for p in out.glob("r*.png"):
            p.unlink()

    for code, title, fn in selected:
        img = render_one(fn, args.size)
        for out in outs:
            path = out / f"{code}.png"
            img.save(path, "PNG", optimize=True)
            print(f"✓ {path}  ({title})", flush=True)


if __name__ == "__main__":
    main()
