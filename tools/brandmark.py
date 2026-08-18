"""Знак марки: тёплый факел с nested тёмным силуэтом (вариант r3-06 dawn).

Канон — файл из сессии BotFather (99aea91): плоский колодец,
градиент оранж → малина → тёмная малина, без сердца, без искры, без 3D.

Источник правды для make_icons / make_banners / BrandMark.tsx.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from PIL import Image, ImageDraw

# Тёплая палитра знака (вариант r3-06 dawn)
ОРАНЖ = (255, 122, 26)         # #ff7a1a — верх
МАЛИНОВЫЙ = (255, 45, 111)     # #ff2d6f — середина / --color-accent
МАЛИНА_ТЁМНАЯ = (184, 22, 72)  # #b81648 — низ
ФОН = (10, 11, 15)

СЕРЫЙ_А = (99, 105, 115)
СЕРЫЙ_Б = (62, 67, 76)

ШИРИНА = 2.0
ВЫСОТА = 2.0

_OUTER_100 = (
    "M 50.000,81.494 C 35.850,72.061 31.470,57.236 36.523,43.760 "
    "C 40.566,33.652 46.631,24.893 52.021,19.165 "
    "C 54.043,27.588 55.391,35.000 56.738,40.391 "
    "C 60.107,32.642 64.150,24.219 68.530,21.523 "
    "C 69.541,30.957 67.520,41.738 66.172,50.498 "
    "C 68.530,60.605 64.150,70.713 57.412,78.125 "
    "C 53.369,82.168 51.348,82.842 50.000,81.494 Z"
)
# Nested гнездо: ушки как у r3-06, долина стыка ~45.5 (было ~48.9),
# чтобы шарды сходились без белого сливера на растеризации.
_NEST_100 = (
    "M 50.391,66.523 C 44.320,62.477 42.441,56.117 44.609,50.336 "
    "C 46.344,46.000 48.945,42.242 51.258,39.785 "
    "C 52.000,42.200 52.600,44.200 53.350,45.500 "
    "C 54.200,44.200 55.800,42.200 58.340,40.797 "
    "C 58.773,44.844 57.906,49.469 57.328,53.227 "
    "C 58.340,57.563 56.461,61.898 53.570,65.078 "
    "C 51.836,66.812 50.969,67.102 50.391,66.523 Z"
)

_UNIT_HALF = 31.16

ФАКЕЛ_PATH_100 = f"{_OUTER_100} {_NEST_100}"
ГНЕЗДО_PATH_100 = _NEST_100


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _mix(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return (
        int(_lerp(c1[0], c2[0], t)),
        int(_lerp(c1[1], c2[1], t)),
        int(_lerp(c1[2], c2[2], t)),
    )


def _bezier(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    steps: int = 14,
) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for i in range(steps + 1):
        t = i / steps
        u = 1.0 - t
        x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
        y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
        pts.append((x, y))
    return pts


def _полигон_из_path(d: str) -> list[tuple[float, float]]:
    token = re.compile(r"([MCZ])|([-+]?(?:\d+\.?\d*|\.\d+))")
    flat: list[str | float] = []
    for cmd, num in token.findall(d.replace(",", " ")):
        flat.append(cmd if cmd else float(num))
    pts: list[tuple[float, float]] = []
    i = 0
    cur = (0.0, 0.0)
    while i < len(flat):
        c = flat[i]
        if c == "M":
            cur = (float(flat[i + 1]), float(flat[i + 2]))
            pts.append(cur)
            i += 3
        elif c == "C":
            p1 = (float(flat[i + 1]), float(flat[i + 2]))
            p2 = (float(flat[i + 3]), float(flat[i + 4]))
            p3 = (float(flat[i + 5]), float(flat[i + 6]))
            seg = _bezier(cur, p1, p2, p3, steps=16)
            pts.extend(seg[1:])
            cur = p3
            i += 7
        elif c == "Z":
            i += 1
        else:
            raise ValueError(f"unsupported path token: {c!r}")
    return pts


def _масштаб(pts: list[tuple[float, float]], cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    s = r / _UNIT_HALF
    return [(cx + (x - _ЯКОРЬ_X) * s, cy + (y - _ЯКОРЬ_Y) * s) for x, y in pts]


def _com_кольца(
    outer: list[tuple[float, float]],
    nest: list[tuple[float, float]],
    res: int = 1000,
    ear_boost: float = 0.85,
) -> tuple[float, float]:
    scale = res / 100.0
    canvas = Image.new("L", (res, res), 0)
    draw = ImageDraw.Draw(canvas)
    draw.polygon([(x * scale, y * scale) for x, y in outer], fill=255)
    draw.polygon([(x * scale, y * scale) for x, y in nest], fill=0)

    ys_o = [p[1] for p in outer]
    y0 = min(ys_o) * scale
    y1 = max(ys_o) * scale
    span = max(y1 - y0, 1.0)
    ear_cut = y0 + span / 3.0

    sum_x = 0.0
    sum_y = 0.0
    n = 0
    sum_x_ear = 0.0
    w_ear = 0.0
    px = canvas.load()
    for y in range(res):
        ear_w = 1.0 + ear_boost if y < ear_cut else 1.0
        for x in range(res):
            if px[x, y]:
                sum_x += x
                sum_y += y
                n += 1
                sum_x_ear += x * ear_w
                w_ear += ear_w
    if n == 0 or w_ear <= 0:
        return 50.0, 50.0
    return sum_x_ear / w_ear / scale, sum_y / n / scale


_OUTER_POLY = _полигон_из_path(_OUTER_100)
_NEST_POLY = _полигон_из_path(_NEST_100)
_ЯКОРЬ_X, _ЯКОРЬ_Y = _com_кольца(_OUTER_POLY, _NEST_POLY)


def _градиент_вертикаль(
    size: tuple[int, int],
    верх: tuple[int, int, int],
    низ: tuple[int, int, int],
    середина: tuple[int, int, int] | None = None,
) -> Image.Image:
    w, h = size
    мелкий = 64
    g = Image.new("RGB", (мелкий, мелкий))
    px = g.load()
    den = мелкий - 1
    for y in range(мелкий):
        t = y / den
        if середина is None:
            c = _mix(верх, низ, t)
        elif t < 0.45:
            c = _mix(верх, середина, t / 0.45)
        else:
            c = _mix(середина, низ, (t - 0.45) / 0.55)
        for x in range(мелкий):
            px[x, y] = c
    return g.resize((w, h), Image.BILINEAR)


def нарисовать_знак(
    img: Image.Image,
    cx: float,
    cy: float,
    r: float,
    приглушить: bool = False,
) -> None:
    if r < 1:
        return

    if приглушить:
        верх, середина, низ = СЕРЫЙ_А, _mix(СЕРЫЙ_А, СЕРЫЙ_Б, 0.45), СЕРЫЙ_Б
    else:
        верх, середина, низ = ОРАНЖ, МАЛИНОВЫЙ, МАЛИНА_ТЁМНАЯ

    ss = 4
    w, h = img.size
    big = (w * ss, h * ss)
    outer = _масштаб(_OUTER_POLY, cx * ss, cy * ss, r * ss)
    nest = _масштаб(_NEST_POLY, cx * ss, cy * ss, r * ss)

    маска = Image.new("L", big, 0)
    draw_m = ImageDraw.Draw(маска)
    draw_m.polygon(outer, fill=255)
    draw_m.polygon(nest, fill=0)
    маска = маска.resize((w, h), Image.LANCZOS)

    градиент = _градиент_вертикаль(img.size, верх, низ, середина).convert("RGBA")
    градиент.putalpha(маска)

    база = img.convert("RGBA")
    база.alpha_composite(градиент)
    img.paste(база.convert(img.mode))


def сделать_mono_white(size: int = 1024) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    r = size * 0.36
    cx = cy = size * 0.5
    ss = 4
    big = (size * ss, size * ss)
    маска = Image.new("L", big, 0)
    d = ImageDraw.Draw(маска)
    d.polygon(_масштаб(_OUTER_POLY, cx * ss, cy * ss, r * ss), fill=255)
    d.polygon(_масштаб(_NEST_POLY, cx * ss, cy * ss, r * ss), fill=0)
    маска = маска.resize((size, size), Image.LANCZOS)
    белый = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    белый.putalpha(маска)
    img.alpha_composite(белый)
    return img


def svg_знак(
    *,
    mono_white: bool = False,
    view: int = 100,
) -> str:
    if mono_white:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view} {view}" '
            f'width="{view}" height="{view}" fill="none" '
            f'role="img" aria-label="Симп">\n'
            f"  <!-- r3-06 well. Геометрия = tools/brandmark.py -->\n"
            f'  <path fill-rule="evenodd" d="{ФАКЕЛ_PATH_100}" fill="#ffffff"/>\n'
            f"</svg>\n"
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view} {view}" '
        f'width="{view}" height="{view}" fill="none" '
        f'role="img" aria-label="Симп">\n'
        f"  <!-- nested torch r3-06. Геометрия = tools/brandmark.py -->\n"
        f"  <defs>\n"
        f'    <linearGradient id="dawn" x1="36" y1="18" x2="60" y2="82" '
        f'gradientUnits="userSpaceOnUse">\n'
        f'      <stop offset="0%" stop-color="#ff7a1a"/>\n'
        f'      <stop offset="45%" stop-color="#ff2d6f"/>\n'
        f'      <stop offset="100%" stop-color="#b81648"/>\n'
        f"    </linearGradient>\n"
        f"  </defs>\n"
        f'  <path fill-rule="evenodd" d="{ФАКЕЛ_PATH_100}" fill="url(#dawn)"/>\n'
        f"</svg>\n"
    )


def сделать_знак(
    size: int = 512,
    bg: tuple[int, int, int] = ФОН,
) -> Image.Image:
    img = Image.new("RGB", (size, size), bg)
    нарисовать_знак(img, size * 0.5, size * 0.5, size * 0.36)
    return img


сделать_знак_с_сердцем = сделать_знак


def main() -> None:
    parser = argparse.ArgumentParser(description="Simp nested torch preview")
    parser.add_argument("--out", default="/tmp/simp-flame.png")
    parser.add_argument("--size", type=int, default=640)
    args = parser.parse_args()
    img = сделать_знак(args.size, ФОН)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out, "PNG")
    print(f"wrote {args.out} anchor=({_ЯКОРЬ_X:.2f},{_ЯКОРЬ_Y:.2f})")


if __name__ == "__main__":
    main()
