"""Знак марки: одна искра мэтча, внутри — капля (душа).

У каждого человека свой цвет — аура (web/src/lib/aura.ts). Мэтч —
встреча двух аур: это градиент малины и фиолета на ОДНОЙ форме.
Знак не склеивает круги и венны: доминирует мягкая 4-лучевая искра
(вспышка мэтча), внутри — одна капля (soul). Как у Мимолёта
вложенность «звезда → сердце», только своя геометрия.

Плоский, статичный. Лёгкий градиент малина → фиолет — заливка формы,
не объём. Читается в 16px (силуэт искры + светлая капля) и в 1024px.

Геометрия одна на все носители: iOS-иконка, сплэш, favicon, баннеры
(make_icons.py, make_banners.py) импортируют её отсюда; SVG на
лендинге и React (web/src/components/BrandMark.tsx) повторяют те же
пропорции. Константы ниже — источник правды.

Пропорции от радиуса описанной окружности R (половина «размаха» искры):
    вершины искры по осям на расстоянии R от центра
    капля: характерный размер ≈ 0.28 R
"""

from __future__ import annotations

import math
from PIL import Image, ImageDraw

# Палитра дизайн-системы (web/src/styles/globals.css)
МАЛИНОВЫЙ = (255, 45, 111)   # --color-accent #ff2d6f — первая аура
ФИОЛЕТОВЫЙ = (139, 92, 246)  # --color-mark-b #8b5cf6 — вторая аура
СВЕТ = (250, 251, 252)       # --color-text #fafbfc — вписанная капля

# Приглушённый вариант — для «серых» носителей (баннер «Дальше»)
СЕРЫЙ_А = (99, 105, 115)
СЕРЫЙ_Б = (62, 67, 76)

#: Искра вписана в квадрат 2R × 2R.
ШИРИНА = 2.0
ВЫСОТА = 2.0


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _mix(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return (
        int(_lerp(c1[0], c2[0], t)),
        int(_lerp(c1[1], c2[1], t)),
        int(_lerp(c1[2], c2[2], t)),
    )


def _точка_искры(cx: float, cy: float, r: float, угол: float) -> tuple[float, float]:
    """Полярная кривая мягкой 4-лучевой искры.

    r(θ) = R · ( |cos 2θ|^n + |sin 2θ|^n )^(-1/(2n)), n≈0.85 —
    лучи без «ножевой» звезды, силуэт ближе к вспышке мэтча.
    """
    n = 0.85
    c = abs(math.cos(2 * угол)) ** n
    s = abs(math.sin(2 * угол)) ** n
    радиус = r / max(1e-6, (c + s) ** (1 / (2 * n)))
    return cx + радиус * math.cos(угол), cy + радиус * math.sin(угол)


def _полигон_искры(cx: float, cy: float, r: float, шагов: int = 160) -> list[tuple[float, float]]:
    return [
        _точка_искры(cx, cy, r, (i / шагов) * math.tau - math.pi / 2)
        for i in range(шагов)
    ]


def _полигон_капли(cx: float, cy: float, r: float, шагов: int = 72) -> list[tuple[float, float]]:
    """Одна капля (soul): единый контур, остриё сверху.

    Параметризация: x = a(1−sin t)cos t, y = a(1−sin t); остриё при t=π/2.
    """
    a = r * 0.28
    точки: list[tuple[float, float]] = []
    for i in range(шагов):
        t = (i / шагов) * math.tau
        s = 1.0 - math.sin(t)
        x = a * 1.12 * s * math.cos(t)
        y = a * 1.35 * s
        # остриё (y≈0) выше центра; тело ниже
        точки.append((cx + x, cy + y - a * 0.85))
    return точки


def _градиент_диагональ(
    size: tuple[int, int],
    цвет_а: tuple[int, int, int],
    цвет_б: tuple[int, int, int],
) -> Image.Image:
    """Быстрый диагональный градиент через маленький холст."""
    w, h = size
    мелкий = 64
    g = Image.new("RGB", (мелкий, мелкий))
    px = g.load()
    den = 2 * (мелкий - 1)
    for y in range(мелкий):
        for x in range(мелкий):
            px[x, y] = _mix(цвет_а, цвет_б, (x + y) / den)
    return g.resize((w, h), Image.BILINEAR)


def нарисовать_знак(
    img: Image.Image,
    cx: float,
    cy: float,
    r: float,
    приглушить: bool = False,
) -> None:
    """Рисует знак на изображении. (cx, cy) — центр, r — радиус описанной окружности."""
    if r < 1:
        return

    а, б = (СЕРЫЙ_А, СЕРЫЙ_Б) if приглушить else (МАЛИНОВЫЙ, ФИОЛЕТОВЫЙ)
    свет = СВЕТ if not приглушить else _mix(СЕРЫЙ_А, (210, 212, 216), 0.65)

    маска = Image.new("L", img.size, 0)
    ImageDraw.Draw(маска).polygon(_полигон_искры(cx, cy, r), fill=255)

    градиент = _градиент_диагональ(img.size, а, б).convert("RGBA")
    градиент.putalpha(маска)

    слой = Image.new("RGBA", img.size, (0, 0, 0, 0))
    слой.alpha_composite(градиент)

    draw = ImageDraw.Draw(слой)
    draw.polygon(_полигон_капли(cx, cy, r), fill=(*свет, 255))

    база = img.convert("RGBA")
    база.alpha_composite(слой)
    img.paste(база.convert(img.mode))
