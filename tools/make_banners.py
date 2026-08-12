#!/usr/bin/env python3
"""Генератор баннеров бота.

Баннеры вели на `placehold.co` — внешний сервис, то есть каждый пользователь
видел чужую картинку, а мы зависели от чужой доступности и отдавали ему
статистику показов. Плюс цвет там остался прежним холодным индиго, который в
продукте уже заменён.

Рисуем сами: фон, знак марки (тот же, что на иконке приложения), надпись.
Файлы кладём в `web/public/banners`, бот берёт их по SITE_URL — то есть со
своего домена.

Знак — «две ауры» из tools/brandmark.py: два пересекающихся кольца-ауры,
в пересечении свет. Геометрия импортируется, а не копируется, поэтому
иконка на телефоне и баннер в боте — буквально одна форма.

Запуск: python3 tools/make_banners.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from brandmark import нарисовать_знак

КОРЕНЬ = Path(__file__).resolve().parent.parent
ВЫХОД = КОРЕНЬ / "web" / "public" / "banners"

# Палитра дизайн-системы (web/src/styles/globals.css)
ФОН = (10, 11, 15)            # --color-bg      #0a0b0f
АКЦЕНТ_ТЁМНЫЙ = (214, 30, 90) # --color-accent-deep #d61e5a
СВЕТЛЫЙ = (250, 251, 252)     # --color-text    #fafbfc

#: (файл, ширина, высота, надпись, приглушить знак)
#: Приглушённый вариант — у «отказных» сюжетов: полноцветный знак на
#: баннере «Дальше» обещал бы радость там, где человек листает мимо.
БАННЕРЫ = [
    ("welcome", 900, 600, "Souldawn", False),
    ("menu", 900, 450, "Souldawn", False),
    ("match", 900, 600, "Взаимно!", False),
    ("profile", 900, 600, "Моя анкета", False),
    ("like", 900, 300, "Нравится", False),
    ("dislike", 900, 300, "Дальше", True),
    ("deck", 900, 1200, "Фото", True),
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


def собрать() -> list[str]:
    ВЫХОД.mkdir(parents=True, exist_ok=True)
    сделано = []

    for имя, ш, в, надпись, приглушить in БАННЕРЫ:
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

        # Радиус круга знака: полная ширина знака ≈ 3.16 r (см. brandmark.py)
        r = max(24, min(ш, в) // 8)
        cy = в // 2 - (r // 2 if в > 320 else 0)
        нарисовать_знак(im, ш // 2, cy, r, приглушить=приглушить)

        f = _шрифт(max(28, min(ш, в) // 11))
        рамка = d.textbbox((0, 0), надпись, font=f)
        # Нижняя кромка знака — cy + 1.36 r (нижнее кольцо смещено вниз)
        d.text(
            ((ш - (рамка[2] - рамка[0])) // 2, cy + int(r * 1.36) + max(18, в // 22)),
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
