"""Знак марки: факел рассвета с nested тёмным силуэтом (r3-06 dawn).

Снаружи — силуэт пламени/факела, градиент оранж → малина.
Внутри — тёмное гнездо той же формы («ушки»), без отдельного глифа
(+, бар, искра) и без крупного сердца, ломающего контур.

Геометрия — исходный r3-06-dawn (viewBox 1024→100), долина стыка
внутренних шардов поднята, чтобы убрать белый сливер. Растр через
4× supersample — PIL polygon без него оставлял светлую щель на AA.

Источник правды для make_icons / make_banners; SVG на лендинге и
React (BrandMark.tsx) повторяют те же контуры.
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
# Масштаб из r3-06-dawn.svg (1024): ×100/1024.
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

# Половина высоты внешнего пламени в unit-space (для масштаба r).
# (81.494 − 19.165) / 2 ≈ 31.16
_UNIT_HALF = 31.16

# Публичный path для сверки со SVG-носителями (outer + nest, evenodd).
ФАКЕЛ_PATH_100 = f"{_OUTER_100} {_NEST_100}"

# r3-06 асимметричен: левое ухо шире, правый кончик дальше.
# Геометрический якорь path (50,50) ≠ bbox-центр силуэта — без сдвига
# марка уезжает вправо/вниз на квадрате и под круглой маской Telegram.
# Якорь пересчитывается после разбора полигона (см. ниже).


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
    """Масштаб в пиксели: (cx, cy) — оптический центр (bbox силуэта)."""
    s = r / _UNIT_HALF
    return [(cx + (x - _ЯКОРЬ_X) * s, cy + (y - _ЯКОРЬ_Y) * s) for x, y in pts]


_OUTER_POLY = _полигон_из_path(_OUTER_100)
_NEST_POLY = _полигон_из_path(_NEST_100)

# Оптический якорь = центр bbox внешнего силуэта (равномерные поля,
# ушки не прилипают к круглой маске с одной стороны).
_xs_outer = [p[0] for p in _OUTER_POLY]
_ys_outer = [p[1] for p in _OUTER_POLY]
_ЯКОРЬ_X = (min(_xs_outer) + max(_xs_outer)) / 2.0
_ЯКОРЬ_Y = (min(_ys_outer) + max(_ys_outer)) / 2.0


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

    # 4× supersample: иначе PIL polygon оставляет светлую щель на стыке шардов.
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
