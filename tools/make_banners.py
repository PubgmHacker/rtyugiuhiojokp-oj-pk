#!/usr/bin/env python3
"""Генератор баннеров бота.

Баннеры вели на `placehold.co` — внешний сервис, то есть каждый пользователь
видел чужую картинку, а мы зависели от чужой доступности и отдавали ему
статистику показов. Плюс цвет там остался прежним холодным индиго, который в
продукте уже заменён.

Рисуем сами: фон, знак-сердце (тот же, что на иконке приложения), надпись.
Файлы кладём в `web/public/banners`, бот берёт их по SITE_URL — то есть со
своего домена.

Знак — именно сердце, а не «восход»: название продукта случайное, и
рисовать под него рассвет значило бы выдумывать бренд из ничего. Сердце
уже стоит на иконке и сплэше — баннер обязан быть той же марки.

Запуск: python3 tools/make_banners.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

КОРЕНЬ = Path(__file__).resolve().parent.parent
ВЫХОД = КОРЕНЬ / "web" / "public" / "banners"

# Палитра дизайн-системы (web/src/styles/globals.css)
ФОН = (10, 11, 15)            # --color-bg      #0a0b0f
АКЦЕНТ = (255, 45, 111)       # --color-accent  #ff2d6f
АКЦЕНТ_ТЁМНЫЙ = (214, 30, 90) # --color-accent-deep #d61e5a
СВЕТЛЫЙ = (250, 251, 252)     # --color-text    #fafbfc
СЕРЫЙ = (155, 161, 171)       # --color-text-muted #9ba1ab

#: (файл, ширина, высота, надпись, цвет знака)
БАННЕРЫ = [
    ("welcome", 900, 600, "Souldawn", АКЦЕНТ),
    ("menu", 900, 450, "Souldawn", АКЦЕНТ),
    ("match", 900, 600, "Взаимно!", АКЦЕНТ),
    ("profile", 900, 600, "Моя анкета", АКЦЕНТ),
    ("like", 900, 300, "Нравится", АКЦЕНТ),
    ("dislike", 900, 300, "Дальше", СЕРЫЙ),
    ("deck", 900, 1200, "Фото", СЕРЫЙ),
]


def _шрифт(размер: int):
    """Системный шрифт; если его нет — встроенный, чтобы генератор не падал."""
    # Порядок важен: Futura, стоявшая тут раньше, кириллицы НЕ содержит, и
    # надписи выходили квадратами. Поэтому шрифт не просто открываем, а
    # проверяем, что нужные буквы в нём есть.
    for путь in (
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Supplemental/Verdana.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Geneva.ttf",
    ):
        try:
            f = ImageFont.truetype(путь, размер)
        except OSError:
            continue
        if f.getmask("Привет").getbbox():
            return f
    return ImageFont.load_default()


def _сердце(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int, цвет) -> None:
    """Знак марки: параметрическое сердце — та же кривая, что в make_icons.py.

    Одна формула в двух генераторах, чтобы иконка на телефоне и баннер в
    боте были буквально одной формой, а не «похожими сердечками».
    """
    масштаб = r / 16.5
    точки = []
    for i in range(220):
        t = 2 * math.pi * i / 220
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        точки.append((cx + x * масштаб, cy - y * масштаб + r * 0.08))
    d.polygon(точки, fill=цвет)


def собрать() -> list[str]:
    ВЫХОД.mkdir(parents=True, exist_ok=True)
    сделано = []

    for имя, ш, в, надпись, цвет in БАННЕРЫ:
        im = Image.new("RGB", (ш, в), ФОН)
        d = ImageDraw.Draw(im)

        # Слабое свечение акцента сверху: плоская заливка выглядит мёртвой
        for i in range(в // 2):
            k = 1 - i / (в / 2)
            d.line(
                [(0, i), (ш, i)],
                fill=(
                    int(ФОН[0] + (АКЦЕНТ_ТЁМНЫЙ[0] - ФОН[0]) * k * 0.22),
                    int(ФОН[1] + (АКЦЕНТ_ТЁМНЫЙ[1] - ФОН[1]) * k * 0.22),
                    int(ФОН[2] + (АКЦЕНТ_ТЁМНЫЙ[2] - ФОН[2]) * k * 0.22),
                ),
            )

        r = max(28, min(ш, в) // 7)
        cy = в // 2 - (r // 2 if в > 320 else 0)
        _сердце(d, ш // 2, cy, r, цвет)

        f = _шрифт(max(28, min(ш, в) // 11))
        рамка = d.textbbox((0, 0), надпись, font=f)
        d.text(
            ((ш - (рамка[2] - рамка[0])) // 2, cy + r + max(18, в // 22)),
            надпись, font=f, fill=СВЕТЛЫЙ,
        )

        путь = ВЫХОД / f"{имя}.png"
        im.save(путь, "PNG", optimize=True)
        сделано.append(имя)

    return сделано


if __name__ == "__main__":
    итог = собрать()
    всего = sum((ВЫХОД / f"{n}.png").stat().st_size for n in итог)
    print(f"Нарисовано баннеров: {len(итог)} ({всего // 1024} КБ)")
    print(f"Папка: {ВЫХОД}")
