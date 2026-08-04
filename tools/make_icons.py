#!/usr/bin/env python3
"""
Генератор иконки, splash-экрана и favicon Souldawn.

Иконка — сплошной акцентный квадрат с белым сердцем. Сознательно без
градиента и свечения: многоцветная заливка на мелком размере смазывается
в грязное пятно, а на домашнем экране рядом с системными иконками
читается как развлекательное приложение.

Цвета берутся из дизайн-системы (web/src/styles/globals.css), чтобы
иконка, splash и интерфейс выглядели одним продуктом.

Запуск:  python3 tools/make_icons.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
IOS_ASSETS = ROOT / "web" / "ios" / "App" / "App" / "Assets.xcassets"
WEB_PUBLIC = ROOT / "web" / "public"

# ── Палитра дизайн-системы ──────────────────────────────────────
BG = (10, 11, 15)            # #0a0b0f
ACCENT = (91, 102, 255)      # #5b66ff
WHITE = (255, 255, 255)


def heart_polygon(cx: float, cy: float, scale: float, steps: int = 220):
    """Параметрическое сердце: гладкая форма без ручных кривых Безье."""
    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((cx + x * scale, cy - y * scale))
    return pts


def make_icon(size: int = 1024) -> Image.Image:
    """Иконка приложения: акцентный фон, белое сердце по центру.

    Углы не скругляем — iOS и Android накладывают собственную маску,
    а предварительное скругление дало бы двойную обводку.
    """
    img = Image.new("RGB", (size, size), ACCENT)

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).polygon(
        heart_polygon(size * 0.5, size * 0.52, size * 0.0245), fill=255
    )
    # Микро-размытие сглаживает края многоугольника
    mask = mask.filter(ImageFilter.GaussianBlur(size * 0.0015))

    img.paste(Image.new("RGB", (size, size), WHITE), (0, 0), mask)
    return img


def make_splash(w: int = 2732, h: int = 2732) -> Image.Image:
    """Splash: тёмный фон и акцентный бейдж с сердцем по центру."""
    img = Image.new("RGB", (w, h), BG)

    badge = int(min(w, h) * 0.14)
    radius = int(badge * 0.23)

    tile = Image.new("RGB", (badge, badge), ACCENT)
    corner = Image.new("L", (badge, badge), 0)
    ImageDraw.Draw(corner).rounded_rectangle([0, 0, badge - 1, badge - 1], radius, fill=255)

    heart = Image.new("L", (badge, badge), 0)
    ImageDraw.Draw(heart).polygon(
        heart_polygon(badge * 0.5, badge * 0.52, badge * 0.0245), fill=255
    )
    tile.paste(Image.new("RGB", (badge, badge), WHITE), (0, 0), heart)

    img.paste(tile, ((w - badge) // 2, (h - badge) // 2), corner)
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

    # Favicon с несколькими размерами внутри
    icon.resize((64, 64), Image.LANCZOS).save(
        WEB_PUBLIC / "favicon.ico", "ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)]
    )
    print(f"✓ {WEB_PUBLIC / 'favicon.ico'}")

    # Превью ссылки в соцсетях и мессенджерах
    og = make_splash(1200, 630)
    og.save(WEB_PUBLIC / "og-image.png", "PNG")
    print(f"✓ {WEB_PUBLIC / 'og-image.png'}")


if __name__ == "__main__":
    main()
