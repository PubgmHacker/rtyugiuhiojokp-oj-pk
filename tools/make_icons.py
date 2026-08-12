#!/usr/bin/env python3
"""
Генератор иконки, splash-экрана и favicon.

Знак марки — одна искра мэтча с каплей внутри (см. tools/brandmark.py).
Иконка — тёмный квадрат в цвете фона приложения со знаком по центру:
на домашнем экране силуэт искры с градиентом аур читается с расстояния
и не похож ни на пламя, ни на звезду+сердце соседей по нише.

Цвета берутся из дизайн-системы (web/src/styles/globals.css), чтобы
иконка, splash и интерфейс выглядели одним продуктом.

Запуск:  python3 tools/make_icons.py
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image

from brandmark import нарисовать_знак

ROOT = Path(__file__).resolve().parent.parent
IOS_ASSETS = ROOT / "web" / "ios" / "App" / "App" / "Assets.xcassets"
WEB_PUBLIC = ROOT / "web" / "public"

# ── Палитра дизайн-системы ──────────────────────────────────────
BG = (10, 11, 15)            # #0a0b0f — холодная нейтральная база


def make_icon(size: int = 1024) -> Image.Image:
    """Иконка приложения: тёмный фон, знак по центру.

    Углы не скругляем — iOS и Android накладывают собственную маску,
    а предварительное скругление дало бы двойную обводку.

    Радиус описанной окружности 0.36 стороны: габарит знака = 2R ≈ 72%
    ширины — крупно для узнавания и с запасом до маски скругления.
    """
    img = Image.new("RGB", (size, size), BG)
    нарисовать_знак(img, size * 0.5, size * 0.5, size * 0.36)
    return img


def make_splash(w: int = 2732, h: int = 2732) -> Image.Image:
    """Splash: тёмный фон, знак по центру — без плашки-бейджа.

    Знак сам по себе форма, подложка-квадрат вокруг него читалась бы
    как «иконка на экране», а не как экран запуска.
    """
    img = Image.new("RGB", (w, h), BG)
    нарисовать_знак(img, w * 0.5, h * 0.5, min(w, h) * 0.085)
    return img


def main() -> None:
    icon = make_icon(1024)

    # ── iOS ────────────────────────────────────────────────────
    appicon_dir = IOS_ASSETS / "AppIcon.appiconset"
    appicon_dir.mkdir(parents=True, exist_ok=True)
    icon.save(appicon_dir / "AppIcon-512@2x.png", "PNG")
    print(f"✓ {appicon_dir / 'AppIcon-512@2x.png'}")

    splash_dir = IOS_ASSETS / "Splash.imageset"
    splash_dir.mkdir(parents=True, exist_ok=True)
    splash = make_splash()
    for name in (
        "splash-2732x2732.png",
        "splash-2732x2732-1.png",
        "splash-2732x2732-2.png",
    ):
        splash.save(splash_dir / name, "PNG")
    print(f"✓ {splash_dir}/splash-*.png")

    # ── PWA и лендинг ──────────────────────────────────────────
    WEB_PUBLIC.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        icon.resize((size, size), Image.LANCZOS).save(
            WEB_PUBLIC / f"icon-{size}.png", "PNG"
        )
        print(f"✓ {WEB_PUBLIC / f'icon-{size}.png'}")

    icon.resize((180, 180), Image.LANCZOS).save(
        WEB_PUBLIC / "apple-touch-icon.png", "PNG"
    )
    print(f"✓ {WEB_PUBLIC / 'apple-touch-icon.png'}")

    # Favicon: на 16px знак рисуем заново крупнее, а не сжимаем иконку —
    # у уменьшенной копии капля внутри искры замыливается
    fav_sizes = [(16, 16), (32, 32), (48, 48), (64, 64)]
    fav = Image.new("RGB", (64, 64), BG)
    нарисовать_знак(fav, 32, 32, 64 * 0.40)
    fav.save(WEB_PUBLIC / "favicon.ico", "ICO", sizes=fav_sizes)
    print(f"✓ {WEB_PUBLIC / 'favicon.ico'}")

    # Превью ссылки в соцсетях и мессенджерах.
    #
    # Источник правды — landing/og-image.svg: там марка, подпись и
    # декоративная карточка. Раньше здесь стоял make_splash(1200, 630), и
    # запуск генератора молча затирал превью голой иконкой на чёрном —
    # ссылка на сервис знакомств выглядела пустой заглушкой.
    render_og()


def render_og() -> None:
    """Растрирует landing/og-image.svg в оба места, где его ждут.

    Лендинг и веб-клиент раздаются с разных корней, поэтому файл нужен
    и там, и там. Растрируем через rsvg-convert (homebrew librsvg).
    Если его нет — НЕ трогаем существующие PNG: лучше оставить прежнее
    превью, чем заменить его пустым.
    """
    svg = ROOT / "landing" / "og-image.svg"
    targets = [ROOT / "landing" / "og-image.png", WEB_PUBLIC / "og-image.png"]

    rsvg = shutil.which("rsvg-convert")
    if rsvg is None:
        print("⚠ rsvg-convert не найден (brew install librsvg) — og-image.png оставлен как был")
        return

    first = targets[0]
    subprocess.run(
        [rsvg, "-w", "1200", "-h", "630", str(svg), "-o", str(first)],
        check=True,
    )
    for other in targets[1:]:
        shutil.copyfile(first, other)
    for t in targets:
        print(f"✓ {t}")


if __name__ == "__main__":
    main()
