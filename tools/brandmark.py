"""Знак марки: факел рассвета с nested тёмным силуэтом (r3-06 dawn).

Снаружи — силуэт пламени/факела, градиент оранж → малина.
Внутри — тёмное гнездо той же формы («ушки»), без отдельного глифа
(+, бар, искра) и без крупного сердца, ломающего контур.

Геометрия — outer r3-06-dawn (viewBox 1024→100) без изменений силуэта.
Nest открыт ~11% и перераспределён по весу кольца (evenodd): тоньше
пики/ушки, плотнее ножка. Долина стыка шардов сохранена.

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

# Микро-сердце внутри nest — только для A/B variant, не default mark.
# viewBox 100; центр гнезда ~ (51.3, 52.5), компактно чтобы не
# касаться ушек и не читаться как «сердце-факел».
_HEART_100 = (
    "M 51.30,55.55 "
    "C 49.95,54.55 48.95,53.35 48.95,52.05 "
    "C 48.95,51.05 49.70,50.40 50.55,50.40 "
    "C 50.95,50.40 51.30,50.60 51.30,50.60 "
    "C 51.30,50.60 51.65,50.40 52.05,50.40 "
    "C 52.90,50.40 53.65,51.05 53.65,52.05 "
    "C 53.65,53.35 52.65,54.55 51.30,55.55 Z"
)

# Половина высоты внешнего пламени в unit-space (для масштаба r).
# (81.494 − 19.165) / 2 ≈ 31.16
_UNIT_HALF = 31.16

# Публичный path для сверки со SVG-носителями (outer + nest, evenodd).
ФАКЕЛ_PATH_100 = f"{_OUTER_100} {_NEST_100}"
ФАКЕЛ_HEART_PATH_100 = f"{_OUTER_100} {_NEST_100} {_HEART_100}"

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
_HEART_POLY = _полигон_из_path(_HEART_100)

# Оптический якорь = COM цветного кольца (X с весом ушек), не bbox.
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
    с_сердцем: bool = False,
) -> Image.Image:
    """Alpha-маска кольца (outer \\ nest), опционально + микро-сердце."""
    if r < 1:
        return Image.new("L", size, 0)

    ss = 4
    w, h = size
    big = (w * ss, h * ss)
    outer = _масштаб(_OUTER_POLY, cx * ss, cy * ss, r * ss)
    nest = _масштаб(_NEST_POLY, cx * ss, cy * ss, r * ss)

    маска = Image.new("L", big, 0)
    draw_m = ImageDraw.Draw(маска)
    draw_m.polygon(outer, fill=255)
    draw_m.polygon(nest, fill=0)
    if с_сердцем:
        heart = _масштаб(_HEART_POLY, cx * ss, cy * ss, r * ss)
        draw_m.polygon(heart, fill=255)
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

    маска = _маска_знака(img.size, cx, cy, r, с_сердцем=False)
    градиент = _градиент_вертикаль(img.size, верх, низ, середина).convert("RGBA")
    градиент.putalpha(маска)

    база = img.convert("RGBA")
    база.alpha_composite(градиент)
    img.paste(база.convert(img.mode))


def сделать_mono_white(size: int = 1024) -> Image.Image:
    """Белый monochrome master на прозрачном — Liquid Glass / tinted iOS.

    Не заменяет цветной канон. Силуэт = outer \\ nest, без сердца.
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    r = size * 0.36
    маска = _маска_знака(img.size, size * 0.5, size * 0.5, r, с_сердцем=False)
    белый = Image.new("RGBA", img.size, (255, 255, 255, 255))
    белый.putalpha(маска)
    img.alpha_composite(белый)
    return img


def svg_знак(
    *,
    mono_white: bool = False,
    с_сердцем: bool = False,
    view: int = 100,
) -> str:
    """SVG viewBox 100×100 — те же path, что растр."""
    path = ФАКЕЛ_HEART_PATH_100 if с_сердцем else ФАКЕЛ_PATH_100
    if mono_white:
        fill = '#ffffff'
        defs = ""
        fill_attr = fill
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
    heart_note = " + micro-heart (A/B only)" if с_сердцем else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view} {view}" '
        f'width="{view}" height="{view}" fill="none" '
        f'role="img" aria-label="Souldawn">\n'
        f"  <!-- nested torch r3-06{heart_note}. Геометрия = tools/brandmark.py -->\n"
        f"  {defs}"
        f'<path fill-rule="evenodd" d="{path}" fill="{fill_attr}"/>\n'
        f"</svg>\n"
    )


def сделать_знак_с_сердцем(size: int = 512, bg: tuple[int, int, int] = (10, 11, 15)) -> Image.Image:
    """A/B variant: default mark + микро-сердце в nest. Не production default."""
    img = Image.new("RGB", (size, size), bg)
    r = size * 0.36
    маска = _маска_знака(img.size, size * 0.5, size * 0.5, r, с_сердцем=True)
    градиент = _градиент_вертикаль(
        img.size, ОРАНЖ, МАЛИНА_ТЁМНАЯ, МАЛИНОВЫЙ
    ).convert("RGBA")
    градиент.putalpha(маска)
    база = img.convert("RGBA")
    база.alpha_composite(градиент)
    return база.convert("RGB")
