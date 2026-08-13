#!/usr/bin/env python3
"""
Генератор иконки, splash-экрана и favicon.

Знак марки — факел рассвета с nested гнездом (см. tools/brandmark.py).
Иконка — тёмный квадрат в цвете фона приложения со знаком по центру:
на домашнем экране пламя с тёмным силуэтом внутри читается с расстояния;
без отдельного глифа и без крупного сердца.

Цвета берутся из дизайн-системы (web/src/styles/globals.css), чтобы
иконка, splash и интерфейс выглядели одним продуктом.

Запуск:  python3 tools/make_icons.py
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from brandmark import (
    ФАКЕЛ_PATH_100,
    нарисовать_знак,
    сделать_mono_white,
    сделать_знак_с_сердцем,
    svg_знак,
)

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


def make_telegram_avatar(size: int = 640) -> Image.Image:
    """Аватар бота для BotFather /setuserpic.

    Квадрат 640×640, сплошной #0a0b0f без прозрачности. Знак ~50%
    высоты кадра (целевой коридор 48–52%) — safe margin в круглой
    маске Telegram, ушки не режутся. Оптический центр чуть ниже
    геометрического (cy≈0.515): асимметрия ушей компенсируется
    COM-якорем в brandmark, не bbox.
    """
    img = Image.new("RGB", (size, size), BG)
    # 2R/size ≈ 0.50 → r = 0.25; было 0.267 (~54%).
    нарисовать_знак(img, size * 0.5, size * 0.515, size * 0.25)
    return img


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"✓ {path}")


def sync_vector_carriers() -> None:
    """Подтягивает path из brandmark в BrandMark.tsx / landing SVG."""
    path = ФАКЕЛ_PATH_100

    # BrandMark.tsx — константа ФАКЕЛ
    bm = ROOT / "web" / "src" / "components" / "BrandMark.tsx"
    bm_src = bm.read_text(encoding="utf-8")
    import re

    bm_new, n = re.subn(
        r'(const ФАКЕЛ =\n  ")([^"]+)(";)',
        rf"\g<1>{path}\g<3>",
        bm_src,
        count=1,
    )
    if n != 1:
        raise RuntimeError("BrandMark.tsx: не нашёл const ФАКЕЛ")
    bm.write_text(bm_new, encoding="utf-8")
    print(f"✓ {bm} (path sync)")

    # landing/icon.svg — path в <g>
    icon = ROOT / "landing" / "icon.svg"
    icon_src = icon.read_text(encoding="utf-8")
    icon_new, n = re.subn(
        r'(fill-rule="evenodd" d=")([^"]+)(")',
        rf"\g<1>{path}\g<3>",
        icon_src,
        count=1,
    )
    if n != 1:
        raise RuntimeError("landing/icon.svg: не нашёл path")
    icon.write_text(icon_new, encoding="utf-8")
    print(f"✓ {icon} (path sync)")

    # landing/og-image.svg
    og = ROOT / "landing" / "og-image.svg"
    og_src = og.read_text(encoding="utf-8")
    og_new, n = re.subn(
        r'(fill-rule="evenodd" d=")([^"]+)(")',
        rf"\g<1>{path}\g<3>",
        og_src,
        count=1,
    )
    if n != 1:
        raise RuntimeError("landing/og-image.svg: не нашёл path")
    og.write_text(og_new, encoding="utf-8")
    print(f"✓ {og} (path sync)")


def write_mono_and_variants() -> None:
    """Белый mono master + A/B heart variant (не default)."""
    brand = WEB_PUBLIC / "brand"
    brand.mkdir(parents=True, exist_ok=True)

    mono = сделать_mono_white(1024)
    mono_png = brand / "mark-mono-white.png"
    mono.save(mono_png, "PNG")
    print(f"✓ {mono_png}")

    mono_svg = brand / "mark-mono-white.svg"
    _write_text(mono_svg, svg_знак(mono_white=True))

    # Цветной SVG master рядом (для справки / tint pipelines)
    mark_svg = brand / "mark.svg"
    _write_text(mark_svg, svg_знак(mono_white=False))

    variants = WEB_PUBLIC / "logo-variants"
    variants.mkdir(parents=True, exist_ok=True)
    heart_svg = variants / "r3-06-dawn-nest-heart.svg"
    _write_text(heart_svg, svg_знак(с_сердцем=True))
    heart_png = variants / "r3-06-dawn-nest-heart.png"
    сделать_знак_с_сердцем(512, BG).save(heart_png, "PNG")
    print(f"✓ {heart_png}")


def write_circle_preview(tg: Image.Image, out: Path) -> None:
    """Круглая маска как в Telegram — для визуальной проверки полей."""
    size = tg.size[0]
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    rgba = tg.convert("RGBA")
    rgba.putalpha(mask)
    # на нейтральном сером, чтобы видеть края
    canvas = Image.new("RGB", (size, size), (40, 42, 48))
    canvas.paste(rgba, mask=mask)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, "PNG")
    print(f"✓ {out}")


def main() -> None:
    sync_vector_carriers()

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
    # у уменьшенной копии гнездо внутри пламени замыливается
    fav_sizes = [(16, 16), (32, 32), (48, 48), (64, 64)]
    fav = Image.new("RGB", (64, 64), BG)
    нарисовать_знак(fav, 32, 32, 64 * 0.40)
    fav.save(WEB_PUBLIC / "favicon.ico", "ICO", sizes=fav_sizes)
    print(f"✓ {WEB_PUBLIC / 'favicon.ico'}")

    # Telegram bot avatar (BotFather): brand/ + копия в корне public.
    tg = make_telegram_avatar(640)
    brand_dir = WEB_PUBLIC / "brand"
    brand_dir.mkdir(parents=True, exist_ok=True)
    tg_brand = brand_dir / "telegram-bot-avatar.png"
    tg_public = WEB_PUBLIC / "telegram-bot-avatar.png"
    tg.save(tg_brand, "PNG")
    shutil.copyfile(tg_brand, tg_public)
    print(f"✓ {tg_brand}")
    print(f"✓ {tg_public}")

    write_circle_preview(tg, Path("/tmp/souldawn-tg-circle-preview.png"))
    write_mono_and_variants()

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
