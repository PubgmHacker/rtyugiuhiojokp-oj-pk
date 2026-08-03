#!/usr/bin/env python3
"""
Генератор иконки и splash-экрана Souldawn.

Рисует «рассвет»: тёмный фон, восходящее солнце-градиент и силуэт сердца.
Цвета взяты из дизайн-системы (web/src/styles/globals.css), чтобы иконка,
splash и интерфейс выглядели одним продуктом.

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
BG = (11, 10, 18)            # #0b0a12
ROSE = (255, 61, 113)        # #ff3d71
CORAL = (255, 122, 92)       # #ff7a5c
GOLD = (255, 196, 107)       # #ffc46b
PLUM = (168, 85, 247)        # #a855f7


def lerp(a: tuple[int, ...], b: tuple[int, ...], t: float) -> tuple[int, ...]:
    """Линейная интерполяция двух цветов."""
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def dawn_gradient(size: int) -> Image.Image:
    """Диагональный градиент «рассвет»: роза → коралл → золото."""
    grad = Image.new("RGB", (size, size))
    px = grad.load()
    stops = [(0.0, ROSE), (0.45, CORAL), (1.0, GOLD)]

    for y in range(size):
        for x in range(size):
            # Диагональная позиция 0..1
            t = (x / size * 0.55) + (y / size * 0.45)
            for i in range(len(stops) - 1):
                t0, c0 = stops[i]
                t1, c1 = stops[i + 1]
                if t0 <= t <= t1:
                    local = (t - t0) / (t1 - t0)
                    px[x, y] = lerp(c0, c1, local)
                    break
            else:
                px[x, y] = stops[-1][1]
    return grad


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
    """Иконка приложения: тёмный фон, световое пятно, сердце-градиент."""
    img = Image.new("RGB", (size, size), BG)
    draw = ImageDraw.Draw(img)

    # Мягкое свечение снизу — «рассвет за горизонтом»
    glow = Image.new("RGB", (size, size), BG)
    gdraw = ImageDraw.Draw(glow)
    for i in range(28, 0, -1):
        r = size * 0.62 * i / 28
        t = 1 - i / 28
        color = lerp(BG, lerp(PLUM, ROSE, 0.65), t * 0.55)
        gdraw.ellipse(
            [size * 0.5 - r, size * 0.92 - r, size * 0.5 + r, size * 0.92 + r],
            fill=color,
        )
    glow = glow.filter(ImageFilter.GaussianBlur(size * 0.05))
    img = Image.blend(img, glow, 0.9)

    # Сердце вырезаем маской из градиента — края остаются чистыми
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).polygon(
        heart_polygon(size * 0.5, size * 0.5, size * 0.0265), fill=255
    )
    mask = mask.filter(ImageFilter.GaussianBlur(size * 0.002))

    heart = dawn_gradient(size)

    # Тень под сердцем для объёма
    shadow = mask.filter(ImageFilter.GaussianBlur(size * 0.035))
    img.paste(Image.new("RGB", (size, size), (0, 0, 0)), (0, int(size * 0.012)), shadow)

    img.paste(heart, (0, 0), mask)

    # Блик по верхней кромке
    shine = Image.new("L", (size, size), 0)
    ImageDraw.Draw(shine).ellipse(
        [size * 0.28, size * 0.24, size * 0.62, size * 0.42], fill=70
    )
    shine = shine.filter(ImageFilter.GaussianBlur(size * 0.03))
    shine = Image.composite(shine, Image.new("L", (size, size), 0), mask)
    img.paste(Image.new("RGB", (size, size), (255, 255, 255)), (0, 0), shine)

    del draw
    return img


def make_splash(w: int = 2732, h: int = 2732) -> Image.Image:
    """Splash: тот же фон и свечение, по центру — уменьшенное сердце."""
    img = Image.new("RGB", (w, h), BG)

    glow = Image.new("RGB", (w, h), BG)
    gdraw = ImageDraw.Draw(glow)
    for i in range(30, 0, -1):
        r = min(w, h) * 0.55 * i / 30
        t = 1 - i / 30
        color = lerp(BG, lerp(PLUM, ROSE, 0.6), t * 0.4)
        gdraw.ellipse([w / 2 - r, h / 2 - r, w / 2 + r, h / 2 + r], fill=color)
    glow = glow.filter(ImageFilter.GaussianBlur(min(w, h) * 0.06))
    img = Image.blend(img, glow, 0.85)

    icon_size = int(min(w, h) * 0.22)
    icon = make_icon(icon_size)

    # Круглая маска, чтобы вписать иконку без резких углов
    mask = Image.new("L", (icon_size, icon_size), 0)
    ImageDraw.Draw(mask).polygon(
        heart_polygon(icon_size * 0.5, icon_size * 0.5, icon_size * 0.0265), fill=255
    )
    img.paste(icon, ((w - icon_size) // 2, (h - icon_size) // 2), mask)
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

    # Картинка для Open Graph (превью ссылки в соцсетях и мессенджерах)
    og = make_splash(1200, 630)
    og.save(WEB_PUBLIC / "og-image.png", "PNG")
    print(f"✓ {WEB_PUBLIC / 'og-image.png'}")


if __name__ == "__main__":
    main()
