#!/usr/bin/env python3
"""Генератор баннеров бота.

Баннеры вели на `placehold.co` — внешний сервис, то есть каждый пользователь
видел чужую картинку, а мы зависели от чужой доступности и отдавали ему
статистику показов. Плюс цвет там остался прежним холодным индиго, который в
продукте уже заменён.

Рисуем сами: фон, знак-круг с мотивом рассвета, надпись. Файлы кладём в
`web/public/banners`, бот берёт их по SITE_URL — то есть со своего домена.

Запуск: python3 tools/make_banners.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

КОРЕНЬ = Path(__file__).resolve().parent.parent
ВЫХОД = КОРЕНЬ / "web" / "public" / "banners"

ФОН = (10, 11, 15)
АКЦЕНТ = (225, 74, 53)
АКЦЕНТ_ТЁМНЫЙ = (194, 58, 39)
СВЕТЛЫЙ = (255, 248, 231)
СЕРЫЙ = (143, 151, 168)

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


def _рассвет(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int, цвет) -> None:
    """Знак марки: полукруг солнца над линией горизонта и лучи.

    Тот же мотив, что у наклейки «Рассвет», — знак должен быть узнаваем и
    здесь, иначе баннер выглядит случайной картинкой.
    """
    d.pieslice(
        [cx - r, cy - r, cx + r, cy + r], start=180, end=360, fill=цвет
    )
    d.rounded_rectangle(
        [cx - int(r * 1.5), cy - 4, cx + int(r * 1.5), cy + 4], radius=4, fill=цвет
    )
    длина = int(r * 0.45)
    for dx, dy in ((0, -1), (-0.72, -0.72), (0.72, -0.72)):
        x0 = cx + int(dx * (r + 14))
        y0 = cy + int(dy * (r + 14))
        d.line(
            [x0, y0, x0 + int(dx * длина), y0 + int(dy * длина)],
            fill=цвет, width=7,
        )


def собрать() -> list[str]:
    ВЫХОД.mkdir(parents=True, exist_ok=True)
    сделано = []

    for имя, ш, в, надпись, цвет in БАННЕРЫ:
        im = Image.new("RGB", (ш, в), ФОН)
        d = ImageDraw.Draw(im)

        # Тёплое свечение сверху: плоская заливка выглядит мёртвой
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
        _рассвет(d, ш // 2, cy, r, цвет)

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
