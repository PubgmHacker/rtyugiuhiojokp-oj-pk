#!/usr/bin/env python3
"""Генератор коллекционных наклеек.

Зачем свои, а не готовые ассеты из интернета: скачанные 3D-модели и стикеры,
даже под CC0, тянут за собой мегабайты, чужую палитру и вечный вопрос «а точно
ли лицензия та, что написана». Здесь наклейки рисуются кодом в SVG — это наша
собственная графика, единицы килобайт, один стиль на всю коллекцию и никакой
зависимости от внешних файлов.

Общая конструкция у всех одна, поэтому набор смотрится семейством, а не
случайной подборкой: круглая подложка с мягким градиентом, поверх — плотный
силуэт-мотив, сверху — блик. Различаются мотивом и оттенком.

Тема — рассвет (Souldawn): солнце, небо, вода, тепло, ночь перед утром.
Редкость задаёт насыщенность подложки: обычные спокойные, легендарные яркие.

Запуск: python3 tools/make_stickers.py
Результат: web/public/stickers/*.svg + оглавление stickers.json
"""

from __future__ import annotations

import json
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
ВЫХОД = КОРЕНЬ / "web" / "public" / "stickers"

#: Оттенки подложки по редкости. Обычные — приглушённые, чтобы редкие
#: выделялись сами, без надписи «редкая».
ФОН = {
    "common": ("#3a4050", "#2a2f3c"),
    "rare": ("#2f6f8f", "#1f4a63"),
    "epic": ("#7a4bb5", "#4e2d7a"),
    "legend": ("#e8a13a", "#d1622a"),
}

#: Мотивы. Ключ — код наклейки, значение — (название, редкость, рисунок).
#: Рисунок в координатах 0..120, цвет мотива всегда светлый: он читается
#: поверх любой подложки.
МОТИВЫ: dict[str, tuple[str, str, str]] = {
    # ── Обычные: небо и погода ───────────────────────────────────
    "sun": ("Солнце", "common", """
        <circle cx="60" cy="60" r="20" fill="#fff8e7"/>
        <g stroke="#fff8e7" stroke-width="5" stroke-linecap="round">
          <path d="M60 26v-9M60 103v-9M26 60h-9M103 60h-9"/>
          <path d="M36 36l-6-6M84 84l6 6M84 36l6-6M36 84l-6 6"/>
        </g>"""),
    "moon": ("Месяц", "common", """
        <path d="M72 26a37 37 0 100 68 30 30 0 010-68z" fill="#fff8e7"/>
        <circle cx="46" cy="44" r="3" fill="#fff8e7" opacity=".7"/>"""),
    "cloud": ("Облако", "common", """
        <path d="M36 74a14 14 0 010-28 20 20 0 0138-6 15 15 0 013 29z"
              fill="#fff8e7"/>"""),
    "star": ("Звезда", "common", """
        <path d="M60 24l10 26 28 2-21 18 7 27-24-15-24 15 7-27-21-18 28-2z"
              fill="#fff8e7"/>"""),
    "rain": ("Дождь", "common", """
        <path d="M38 62a13 13 0 010-26 18 18 0 0134-5 14 14 0 013 27z"
              fill="#fff8e7"/>
        <g stroke="#fff8e7" stroke-width="5" stroke-linecap="round" opacity=".85">
          <path d="M44 74l-4 12M60 74l-4 14M76 74l-4 12"/>
        </g>"""),
    "leaf": ("Лист", "common", """
        <path d="M84 32c6 30-14 54-42 56 2-30 16-50 42-56z" fill="#fff8e7"/>
        <path d="M78 40C62 52 52 66 46 86" stroke="#2a2f3c" stroke-width="4"
              stroke-linecap="round" fill="none" opacity=".45"/>"""),

    # ── Редкие: вода, огонь, горы ────────────────────────────────
    "wave": ("Волна", "rare", """
        <path d="M22 66c12-26 34-30 46-12 8 12 20 12 30-2-2 26-20 38-36 32
                 -10-4-14-14-10-22 3-6 10-8 14-4-8 0-10 6-8 10 4 8 16 6 20-4
                 -6 18-24 22-38 12-8-6-12-12-18-10z" fill="#fff8e7"/>
        <path d="M24 88c10-6 20-6 30 0s22 6 34-2" stroke="#fff8e7"
              stroke-width="5" fill="none" stroke-linecap="round" opacity=".6"/>"""),
    "flame": ("Огонёк", "rare", """
        <path d="M66 18c-4 16-18 22-24 34-6 12-2 26 10 32 14 7 30 0 34-14
                 3-11-2-20-10-26 1 8-3 13-8 14 4-14-2-30-2-40z"
              fill="#fff8e7"/>
        <path d="M46 56c-8 6-12 16-8 25 3 8 11 12 18 11-8-6-11-14-9-22
                 1-6 1-10-1-14z" fill="#fff8e7" opacity=".8"/>
        <path d="M62 62c5 6 7 12 5 17-2 6-8 9-13 7-5-2-7-8-5-14 2-5 8-8 13-10z"
              fill="#d1622a"/>"""),

    "mountain": ("Вершина", "rare", """
        <path d="M20 88l26-42 16 24 10-14 28 32z" fill="#fff8e7"/>
        <path d="M46 46l-9 15h18z" fill="#2a2f3c" opacity=".35"/>"""),
    "feather": ("Перо", "rare", """
        <path d="M86 24c10 24 0 50-22 62l-8-8 22-24-26 18-6-6 24-26-22 14
                 c4-18 20-30 38-30z" fill="#fff8e7"/>
        <path d="M84 26L38 96" stroke="#fff8e7" stroke-width="5"
              stroke-linecap="round"/>"""),
    "key": ("Ключ", "rare", """
        <circle cx="46" cy="46" r="16" fill="none" stroke="#fff8e7" stroke-width="8"/>
        <path d="M56 58l30 30M76 78l10 10M68 86l8 8" stroke="#fff8e7"
              stroke-width="8" stroke-linecap="round"/>"""),
    "lantern": ("Фонарь", "rare", """
        <path d="M46 22a14 14 0 0128 0" stroke="#fff8e7" stroke-width="5"
              fill="none" stroke-linecap="round"/>
        <path d="M40 34h40v8H40zM40 86h40v8H40z" fill="#fff8e7"/>
        <path d="M46 42h28v44H46z" fill="#fff8e7"/>
        <path d="M60 52a10 14 0 000 26 10 14 0 000-26z" fill="#1f4a63"
              opacity=".6"/>"""),

    # ── Эпические: сердце, комета, компас ────────────────────────
    "heart": ("Сердце", "epic", """
        <path d="M60 96S24 72 24 50a19 19 0 0136-9 19 19 0 0136 9c0 22-36 46-36 46z"
              fill="#fff8e7"/>"""),
    "comet": ("Комета", "epic", """
        <!-- Хвост одной сужающейся массой: три параллельные линии из шара
             читались медузой -->
        <path d="M74 30l22 8-52 56-20 6 8-20z" fill="#fff8e7" opacity=".55"/>
        <circle cx="82" cy="38" r="16" fill="#fff8e7"/>
        <path d="M30 90l-6 6" stroke="#fff8e7" stroke-width="5"
              stroke-linecap="round" opacity=".8"/>"""),

    "compass": ("Компас", "epic", """
        <circle cx="60" cy="60" r="33" fill="none" stroke="#fff8e7" stroke-width="6"/>
        <!-- Двухцветная стрелка: у одноцветной не видно, где север -->
        <path d="M60 30l11 30-11 8-11-8z" fill="#fff8e7"/>
        <path d="M60 90l-11-30 11-8 11 8z" fill="#fff8e7" opacity=".45"/>
        <circle cx="60" cy="60" r="4" fill="#4e2d7a"/>"""),

    "eye": ("Око", "epic", """
        <path d="M20 60c14-20 26-28 40-28s26 8 40 28c-14 20-26 28-40 28s-26-8-40-28z"
              fill="#fff8e7"/>
        <circle cx="60" cy="60" r="13" fill="#4e2d7a"/>"""),
    "hourglass": ("Песочные часы", "epic", """
        <path d="M38 26h44v10L62 60l20 24v10H38V84l20-24-20-24z" fill="#fff8e7"/>
        <path d="M50 82h20l-10-12z" fill="#4e2d7a" opacity=".6"/>"""),

    # ── Легендарные: рассвет и всё, что редко ────────────────────
    "dawn": ("Рассвет", "legend", """
        <path d="M18 82h84" stroke="#fff8e7" stroke-width="7" stroke-linecap="round"/>
        <path d="M32 82a28 28 0 0156 0z" fill="#fff8e7"/>
        <g stroke="#fff8e7" stroke-width="5" stroke-linecap="round" opacity=".85">
          <path d="M60 34v-10M30 46l-7-7M90 46l7-7"/>
        </g>"""),
    "phoenix": ("Феникс", "legend", """
        <!-- Профиль, а не симметрия: симметричный силуэт глаз читает звездой.
             Голова слева, крыло вверх, хвост вниз-вправо -->
        <path d="M40 46c-6-4-8-10-6-16 6 2 11 6 14 11 6-4 13-5 20-3
                 l24-14-8 20c8 4 13 11 14 20l-16-8c-1 8-6 14-13 17
                 l14 22-24-14-16 16 4-24c-8-4-13-12-13-21 0-2 0-4 1-6z"
              fill="#fff8e7"/>
        <circle cx="44" cy="40" r="3.5" fill="#d1622a"/>
        <path d="M34 41l-9 2 9 3z" fill="#fff8e7"/>"""),

    "crown": ("Венец", "legend", """
        <path d="M26 80l-6-38 22 16 18-28 18 28 22-16-6 38z" fill="#fff8e7"/>
        <path d="M26 84h68v10H26z" fill="#fff8e7"/>"""),
    "diamond": ("Кристалл", "legend", """
        <path d="M60 20l34 26-34 54-34-54z" fill="#fff8e7"/>
        <path d="M60 20L44 46h32zM26 46h68" stroke="#d1622a" stroke-width="4"
              fill="none" opacity=".45"/>"""),
    "constellation": ("Созвездие", "legend", """
        <g stroke="#fff8e7" stroke-width="4" opacity=".7">
          <path d="M32 40l24 16 18-22 22 30-34 22z" fill="none"/>
        </g>
        <g fill="#fff8e7">
          <circle cx="32" cy="40" r="7"/><circle cx="56" cy="56" r="6"/>
          <circle cx="74" cy="34" r="6"/><circle cx="96" cy="64" r="7"/>
          <circle cx="62" cy="86" r="6"/>
        </g>"""),
    "soul": ("Душа", "legend", """
        <circle cx="60" cy="60" r="26" fill="#fff8e7"/>
        <circle cx="60" cy="60" r="38" fill="none" stroke="#fff8e7"
                stroke-width="4" opacity=".55"/>
        <circle cx="60" cy="60" r="13" fill="#d1622a" opacity=".7"/>"""),

    # ── Добор: коллекция должна быть достаточно большой, чтобы её хотелось
    # собрать, но каждая наклейка обязана читаться с 40 пикселей ─────
    "coffee": ("Кофе", "common", """
        <path d="M34 42h44v26a22 22 0 01-44 0z" fill="#fff8e7"/>
        <path d="M78 48h10a10 10 0 010 20h-10z" fill="none" stroke="#fff8e7"
              stroke-width="6"/>
        <g stroke="#fff8e7" stroke-width="4" stroke-linecap="round" opacity=".7">
          <path d="M46 32c0-4 4-6 4-10M60 32c0-4 4-6 4-10"/>
        </g>"""),
    "music": ("Нота", "common", """
        <path d="M50 30l30-8v12l-30 8z" fill="#fff8e7"/>
        <path d="M46 34h6v44h-6zM76 26h6v36h-6z" fill="#fff8e7"/>
        <ellipse cx="38" cy="80" rx="14" ry="10" fill="#fff8e7"/>
        <ellipse cx="68" cy="64" rx="12" ry="9" fill="#fff8e7"/>"""),
    "book": ("Книга", "common", """
        <path d="M28 32c12-6 24-6 32 2v54c-8-8-20-8-32-2z" fill="#fff8e7"/>
        <path d="M92 32c-12-6-24-6-32 2v54c8-8 20-8 32-2z" fill="#fff8e7"
              opacity=".8"/>"""),
    "camera": ("Камера", "common", """
        <path d="M22 42h20l6-8h24l6 8h20v44H22z" fill="#fff8e7"/>
        <circle cx="60" cy="64" r="15" fill="#2a2f3c"/>
        <circle cx="60" cy="64" r="7" fill="#fff8e7" opacity=".6"/>"""),
    "plane": ("Самолёт", "rare", """
        <path d="M96 24L36 56l-16-6-8 8 20 12 6 22 8-8-4-14z" fill="#fff8e7"/>
        <path d="M96 24L52 78l6 18 10-6 4-24z" fill="#fff8e7" opacity=".7"/>"""),
    "anchor": ("Якорь", "rare", """
        <circle cx="60" cy="28" r="9" fill="none" stroke="#fff8e7" stroke-width="6"/>
        <path d="M57 38h6v54h-6z" fill="#fff8e7"/>
        <path d="M40 46h40" stroke="#fff8e7" stroke-width="6" stroke-linecap="round"/>
        <path d="M28 68c0 18 14 28 32 28s32-10 32-28l-10 4c-2 12-10 18-22 18
                 s-20-6-22-18z" fill="#fff8e7"/>"""),
    "clover": ("Клевер", "rare", """
        <g fill="#fff8e7">
          <circle cx="46" cy="46" r="14"/><circle cx="74" cy="46" r="14"/>
          <circle cx="46" cy="70" r="14"/><circle cx="74" cy="70" r="14"/>
        </g>
        <path d="M60 76c2 12 8 18 18 22" stroke="#fff8e7" stroke-width="5"
              fill="none" stroke-linecap="round"/>"""),
    "bell": ("Колокол", "rare", """
        <path d="M60 22a8 8 0 018 8c12 5 18 16 18 30v14l8 10H26l8-10V60
                 c0-14 6-25 18-30a8 8 0 018-8z" fill="#fff8e7"/>
        <path d="M50 90a10 10 0 0020 0z" fill="#fff8e7"/>"""),
    "mask": ("Маска", "epic", """
        <!-- Вырез между глаз и острые края: округлый низ читался сердцем -->
        <path d="M20 46c14-8 28-8 40 2 12-10 26-10 40-2-2 16-8 26-18 32
                 -8 5-16 4-22-2-6 6-14 7-22 2-10-6-16-16-18-32z"
              fill="#fff8e7"/>
        <g fill="#4e2d7a">
          <ellipse cx="40" cy="58" rx="9" ry="6"/>
          <ellipse cx="80" cy="58" rx="9" ry="6"/>
        </g>
        <path d="M60 48v18" stroke="#4e2d7a" stroke-width="4" opacity=".5"/>"""),

    "orbit": ("Орбита", "epic", """
        <circle cx="60" cy="60" r="16" fill="#fff8e7"/>
        <ellipse cx="60" cy="60" rx="42" ry="16" fill="none" stroke="#fff8e7"
                 stroke-width="5" transform="rotate(-25 60 60)"/>
        <circle cx="96" cy="44" r="7" fill="#fff8e7"/>"""),
    "labyrinth": ("Лабиринт", "epic", """
        <g fill="none" stroke="#fff8e7" stroke-width="6" stroke-linecap="square">
          <path d="M26 26h68v68H26z"/>
          <path d="M40 40h40v40H54"/>
          <path d="M54 54h14v14"/>
        </g>"""),
    "aurora": ("Сияние", "legend", """
        <g fill="none" stroke="#fff8e7" stroke-width="7" stroke-linecap="round">
          <path d="M26 88c6-32 16-48 30-48s24 16 30 48" opacity=".9"/>
          <path d="M40 88c4-22 10-34 20-34s16 12 20 34" opacity=".6"/>
        </g>
        <g fill="#fff8e7">
          <circle cx="30" cy="34" r="4"/><circle cx="90" cy="30" r="5"/>
          <circle cx="60" cy="24" r="3"/>
        </g>"""),
    "hummingbird": ("Колибри", "legend", """
        <!-- Длинный клюв и цветок: без них силуэт повторял феникса -->
        <ellipse cx="62" cy="58" rx="17" ry="13" transform="rotate(-20 62 58)"
                 fill="#fff8e7"/>
        <path d="M50 50l-26-12 24 20z" fill="#fff8e7"/>
        <path d="M70 66l16 26-24-14z" fill="#fff8e7"/>
        <path d="M74 46c10-8 18-8 24-2-8 6-16 8-24 6z" fill="#fff8e7" opacity=".75"/>
        <circle cx="56" cy="50" r="3" fill="#d1622a"/>
        <path d="M46 46l-16-6" stroke="#fff8e7" stroke-width="4"
              stroke-linecap="round"/>
        <circle cx="26" cy="38" r="7" fill="#d1622a" opacity=".85"/>"""),

    "eclipse": ("Затмение", "legend", """
        <circle cx="60" cy="60" r="32" fill="#fff8e7"/>
        <circle cx="74" cy="52" r="28" fill="#d1622a"/>
        <g stroke="#fff8e7" stroke-width="5" stroke-linecap="round" opacity=".8">
          <path d="M60 18v-8M60 110v-8M18 60h-8M110 60h-8"/>
        </g>"""),
}

ШАБЛОН = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120"
     width="120" height="120" role="img" aria-label="{название}">
  <title>{название}</title>
  <defs>
    <radialGradient id="ф" cx="35%" cy="28%" r="82%">
      <stop offset="0%" stop-color="{светлый}"/>
      <stop offset="100%" stop-color="{тёмный}"/>
    </radialGradient>
  </defs>
  <circle cx="60" cy="60" r="58" fill="url(#ф)"/>
  {мотив}
  <!-- Блик: без него подложка выглядит плоской заливкой -->
  <ellipse cx="42" cy="30" rx="26" ry="14" fill="#ffffff" opacity=".14"/>
  <circle cx="60" cy="60" r="58" fill="none" stroke="#ffffff"
          stroke-opacity=".18" stroke-width="2"/>
</svg>
"""


def собрать() -> list[dict]:
    ВЫХОД.mkdir(parents=True, exist_ok=True)
    оглавление = []

    for код, (название, редкость, мотив) in МОТИВЫ.items():
        светлый, тёмный = ФОН[редкость]
        svg = ШАБЛОН.format(
            название=название,
            светлый=светлый,
            тёмный=тёмный,
            мотив=мотив.strip(),
        )
        (ВЫХОД / f"{код}.svg").write_text(svg, encoding="utf-8")
        оглавление.append({"code": код, "title": название, "rarity": редкость})

    (ВЫХОД / "stickers.json").write_text(
        json.dumps(оглавление, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return оглавление


if __name__ == "__main__":
    итог = собрать()
    по_редкости: dict[str, int] = {}
    for s in итог:
        по_редкости[s["rarity"]] = по_редкости.get(s["rarity"], 0) + 1
    print(f"Нарисовано наклеек: {len(итог)}")
    for р, n in по_редкости.items():
        print(f"  {р}: {n}")
    print(f"Папка: {ВЫХОД}")
