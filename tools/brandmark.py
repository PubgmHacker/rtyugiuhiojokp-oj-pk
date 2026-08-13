"""Знак марки: факел рассвета + dating-бейдж (сердце в гнезде).

Снаружи — силуэт пламени/факела r3-06, градиент оранж → малина.
Внутри — открытое гнездо (ушки), затем ядро того же силуэта и
тёмное сердце negative-space в оптическом центре nest.
Иерархия как у Mimolet (внешняя форма + dating-noun), без деформации
outer path. Сердце = вырез в цвет ядра/фона (#0a0b0f), не розовая
наклейка и не белый глиф.

Геометрия — outer r3-06-dawn (viewBox 1024→100) без изменений силуэта.
Nest открыт ~11% и перераспределён по весу кольца (evenodd): тоньше
пики/ушки, плотнее ножка. Долина стыка шардов сохранена.
Core = nest ×0.94 от bbox-центра nest; сердце ~20% высоты nest.

Растр через 4× supersample — PIL polygon без него оставлял светлую
щель на AA.

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

# Nested гнездо: канон r3-06, затем morph от центроида nest
# (mid=1.07, top=1.15, bot=0.93) — площадь cutout +~11.5%, ушки
# тоньше (~−10%), ножка плотнее (~+5%). Силуэт outer не трогаем.
_NEST_100 = (
    "M 50.450,65.683 C 44.323,62.473 41.919,56.266 44.070,50.074 "
    "C 45.803,45.173 48.630,40.724 51.251,37.715 "
    "C 52.094,40.674 52.757,43.065 53.580,44.592 "
    "C 54.551,43.065 56.403,40.674 59.349,38.964 "
    "C 59.645,43.824 58.476,49.114 57.743,53.202 "
    "C 58.691,57.762 56.497,61.957 53.480,64.624 "
    "C 51.798,65.881 50.994,66.076 50.450,65.683 Z"
)

# Ядро гнезда: nest ×0.94 от bbox-центра nest — тонкое тёмное кольцо
# ушек остаётся «открытым гнездом», внутри — поверхность под вырез сердца.
_CORE_100 = (
    "M 50.504,64.849 C 44.745,61.832 42.485,55.997 44.507,50.177 "
    "C 46.136,45.570 48.793,41.388 51.257,38.559 "
    "C 52.049,41.341 52.673,43.588 53.446,45.024 "
    "C 54.359,43.588 56.100,41.341 58.869,39.734 "
    "C 59.147,44.302 58.048,49.275 57.359,53.117 "
    "C 58.251,57.404 56.188,61.347 53.352,63.854 "
    "C 51.771,65.036 51.015,65.219 50.504,64.849 Z"
)

# Тёмное сердце в оптическом центре nest (~51.35, 52.0).
# Высота ≈20% nest — читается в круге Telegram и на 32px, не гигант.
_HEART_100 = (
    "M 51.350,54.688 "
    "C 50.654,53.232 48.450,52.112 48.450,50.992 "
    "C 48.450,49.648 50.074,49.200 51.350,50.768 "
    "C 52.626,49.200 54.250,49.648 54.250,50.992 "
    "C 54.250,52.112 52.046,53.232 51.350,54.688 Z"
)

# Половина высоты внешнего пламени в unit-space (для масштаба r).
# (81.494 − 19.165) / 2 ≈ 31.16
_UNIT_HALF = 31.16

# Публичный path: outer \\ nest ∪ core \\ heart (evenodd).
ФАКЕЛ_PATH_100 = f"{_OUTER_100} {_NEST_100} {_CORE_100} {_HEART_100}"

# r3-06 асимметричен: левое ухо шире, правый кончик дальше.
# Геометрический якорь path (50,50) и даже bbox силуэта врут — без
# сдвига по COM кольца марка уезжает вправо/вниз под круглой маской
# Telegram. Якорь — _com_кольца после разбора полигона (см. ниже).


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
    """Масштаб в пиксели: (cx, cy) — оптический центр (COM кольца)."""
    s = r / _UNIT_HALF
    return [(cx + (x - _ЯКОРЬ_X) * s, cy + (y - _ЯКОРЬ_Y) * s) for x, y in pts]


def _com_кольца(
    outer: list[tuple[float, float]],
    nest: list[tuple[float, float]],
    res: int = 1000,
    ear_boost: float = 0.85,
) -> tuple[float, float]:
    """Оптический центр цветного кольца (outer \\ nest) в unit-space path 100.

    Bbox на r3-06 врёт: левое ухо шире, правый кончик дальше — геометрический
    центр даёт поля «математически ровные», а в круглой маске 640 факел
    читается правее/ниже. Y — обычный COM кольца. X — COM с усиленным
    весом верхней трети (ушки), без правки силуэта.
    """
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
        # Ушки тянут восприятие вправо — выше вес по X → якорь правее →
        # контент уходит влево. По Y вес не трогаем (иначе марка тонет).
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
_CORE_POLY = _полигон_из_path(_CORE_100)
_HEART_POLY = _полигон_из_path(_HEART_100)

# Оптический якорь = COM цветного кольца (X с весом ушек), не bbox.
# Считаем по outer\\nest — поля/safe margin как в 3f753cf.
_ЯКОРЬ_X, _ЯКОРЬ_Y = _com_кольца(_OUTER_POLY, _NEST_POLY)


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


def _маска_знака(
    size: tuple[int, int],
    cx: float,
    cy: float,
    r: float,
) -> Image.Image:
    """Alpha-маска: (outer \\ nest) ∪ (core \\ heart)."""
    if r < 1:
        return Image.new("L", size, 0)

    ss = 4
    w, h = size
    big = (w * ss, h * ss)
    outer = _масштаб(_OUTER_POLY, cx * ss, cy * ss, r * ss)
    nest = _масштаб(_NEST_POLY, cx * ss, cy * ss, r * ss)
    core = _масштаб(_CORE_POLY, cx * ss, cy * ss, r * ss)
    heart = _масштаб(_HEART_POLY, cx * ss, cy * ss, r * ss)

    маска = Image.new("L", big, 0)
    draw_m = ImageDraw.Draw(маска)
    draw_m.polygon(outer, fill=255)
    draw_m.polygon(nest, fill=0)
    draw_m.polygon(core, fill=255)
    draw_m.polygon(heart, fill=0)
    return маска.resize((w, h), Image.LANCZOS)


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

    маска = _маска_знака(img.size, cx, cy, r)
    градиент = _градиент_вертикаль(img.size, верх, низ, середина).convert("RGBA")
    градиент.putalpha(маска)

    база = img.convert("RGBA")
    база.alpha_composite(градиент)
    img.paste(база.convert(img.mode))


def сделать_mono_white(size: int = 1024) -> Image.Image:
    """Белый monochrome master на прозрачном — Liquid Glass / tinted iOS.

    Не заменяет цветной канон. Силуэт = outer \\ nest ∪ core \\ heart.
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    r = size * 0.36
    маска = _маска_знака(img.size, size * 0.5, size * 0.5, r)
    белый = Image.new("RGBA", img.size, (255, 255, 255, 255))
    белый.putalpha(маска)
    img.alpha_composite(белый)
    return img


def svg_знак(
    *,
    mono_white: bool = False,
    view: int = 100,
) -> str:
    """SVG viewBox 100×100 — те же path, что растр."""
    path = ФАКЕЛ_PATH_100
    if mono_white:
        defs = ""
        fill_attr = "#ffffff"
    else:
        defs = (
            '<defs>\n'
            '    <linearGradient id="dawn" x1="36" y1="18" x2="60" y2="82" '
            'gradientUnits="userSpaceOnUse">\n'
            '      <stop offset="0%" stop-color="#ff7a1a"/>\n'
            '      <stop offset="45%" stop-color="#ff2d6f"/>\n'
            '      <stop offset="100%" stop-color="#b81648"/>\n'
            "    </linearGradient>\n"
            "  </defs>\n  "
        )
        fill_attr = "url(#dawn)"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view} {view}" '
        f'width="{view}" height="{view}" fill="none" '
        f'role="img" aria-label="Souldawn">\n'
        f"  <!-- nested torch r3-06 + dark heart in nest. "
        f"Геометрия = tools/brandmark.py -->\n"
        f"  {defs}"
        f'<path fill-rule="evenodd" d="{path}" fill="{fill_attr}"/>\n'
        f"</svg>\n"
    )


def сделать_знак(
    size: int = 512,
    bg: tuple[int, int, int] = (10, 11, 15),
) -> Image.Image:
    """Цветной знак на тёмном фоне — production default."""
    img = Image.new("RGB", (size, size), bg)
    r = size * 0.36
    нарисовать_знак(img, size * 0.5, size * 0.5, r)
    return img


# Совместимость со старым именем A/B-хелпера.
сделать_знак_с_сердцем = сделать_знак
