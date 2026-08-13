"""Знак марки: факел рассвета с вложенным сердцем (иерархия как у Мимолёта).

Снаружи — силуэт пламени/факела (r3-06), градиент оранж → малина.
Внутри — сердце negative space, оптически по центру пламени.
Без отдельного глифа (+, искра, черта): гармония за счёт вложенной формы.

Геометрия одна на все носители: iOS-иконка, сплэш, favicon, баннеры
(make_icons.py, make_banners.py) импортируют её отсюда; SVG на
лендинге и React (web/src/components/BrandMark.tsx) повторяют те же
пропорции. Константы ниже — источник правды.

Пропорции в viewBox 100×100 (центр знака ≈ 50,50):
    внешнее пламя по высоте ≈ 83.4
    сердце — continuous tip-down, evenodd-вырез
"""

from __future__ import annotations

import re
from PIL import Image, ImageDraw

# Палитра рассвета (r3-06 dawn)
ОРАНЖ = (255, 122, 26)         # #ff7a1a — верх
МАЛИНОВЫЙ = (255, 45, 111)     # #ff2d6f — середина / --color-accent
МАЛИНА_ТЁМНАЯ = (184, 22, 72)  # #b81648 — низ

# Приглушённый вариант — для «серых» носителей (баннер «Дальше»)
СЕРЫЙ_А = (99, 105, 115)
СЕРЫЙ_Б = (62, 67, 76)

#: Пламя вписано в квадрат примерно 2R × 2R по высоте.
ШИРИНА = 2.0
ВЫСОТА = 2.0

# viewBox 100×100 — те же контуры, что BrandMark.tsx / landing/icon.svg
_OUTER_100 = (
    "M 47.548,89.418 C 28.618,76.798 22.759,56.967 29.520,38.939 "
    "C 34.928,25.418 43.041,13.700 50.252,6.038 "
    "C 52.956,17.306 54.759,27.221 56.562,34.432 "
    "C 61.069,24.066 66.477,12.799 72.336,9.193 "
    "C 73.688,21.813 70.984,36.235 69.181,47.953 "
    "C 72.336,61.474 66.477,74.995 57.463,84.911 "
    "C 52.055,90.319 49.351,91.221 47.548,89.418 Z"
)
_HEART_100 = (
    "M 49.116,40.316 C 42.505,29.860 35.294,34.668 36.496,41.879 "
    "C 36.496,47.888 43.707,52.095 49.116,55.099 "
    "C 54.524,52.095 61.735,47.888 61.735,41.879 "
    "C 62.937,34.668 55.726,29.860 49.116,40.316 Z"
)

# Половина высоты внешнего пламени в unit-space (для масштаба r).
_UNIT_HALF = 41.7


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
    """Растрирует SVG path (M/C/Z, абсолютные) в полигон unit-space."""
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
    return [(cx + (x - 50.0) * s, cy + (y - 50.0) * s) for x, y in pts]


_OUTER_POLY = _полигон_из_path(_OUTER_100)
_HEART_POLY = _полигон_из_path(_HEART_100)


def _градиент_вертикаль(
    size: tuple[int, int],
    верх: tuple[int, int, int],
    низ: tuple[int, int, int],
    середина: tuple[int, int, int] | None = None,
) -> Image.Image:
    """Вертикальный градиент рассвета через маленький холст."""
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
    """Рисует знак на изображении. (cx, cy) — центр, r — половина высоты пламени."""
    if r < 1:
        return

    if приглушить:
        верх, середина, низ = СЕРЫЙ_А, _mix(СЕРЫЙ_А, СЕРЫЙ_Б, 0.45), СЕРЫЙ_Б
    else:
        верх, середина, низ = ОРАНЖ, МАЛИНОВЫЙ, МАЛИНА_ТЁМНАЯ

    outer = _масштаб(_OUTER_POLY, cx, cy, r)
    heart = _масштаб(_HEART_POLY, cx, cy, r)

    маска = Image.new("L", img.size, 0)
    draw_m = ImageDraw.Draw(маска)
    draw_m.polygon(outer, fill=255)
    draw_m.polygon(heart, fill=0)

    градиент = _градиент_вертикаль(img.size, верх, низ, середина).convert("RGBA")
    градиент.putalpha(маска)

    база = img.convert("RGBA")
    база.alpha_composite(градиент)
    img.paste(база.convert(img.mode))
