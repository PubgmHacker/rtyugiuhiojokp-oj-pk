#!/usr/bin/env python3
"""Сборка коллекции наклеек для кейсов из паков stickers.gg.

Три кейса — три набора: «Керопи», «Star Rail» и «Хеллоуин». Источник —
публичные паки stickers.gg (PNG/WebP с прозрачностью). Каждый файл здесь
проходит одну и ту же обработку, чтобы коллекция смотрелась семейством,
а не случайной подборкой картинок разного размера:

1. Прозрачность вычищается: у части исходников по краям лежит бледная
   полупрозрачная дымка (альфа ~40 из 255) — на фото анкеты она читалась бы
   грязным квадратом вокруг персонажа. Всё, что прозрачнее порога, обнуляем.
2. Персонаж обрезается по своим границам и центрируется в квадрате с полем,
   чтобы значок в анкете занимал одинаковую площадь у всех наклеек.
3. Квадрат уменьшается до одного размера и пишется в WebP с альфой: значок в
   анкете — 56–72 CSS-пикселя, 256 px хватает и на Retina ×3.

Оглавление `api/data/stickers.json` — единственный источник правды для API
(`api/services/stickers.py`): код, название, редкость и набор. Картинка
лежит по адресу `/stickers/<набор>/<код>.webp` — путь строится из кода и
набора, в оглавлении не дублируется.

Оглавление лежит внутри `api/`, а не рядом с картинками: сервис API на
Railway собирается из папки `api/` (Dockerfile: `COPY . .`), и папки `web/`
в контейнере нет. Каталог у картинок там просто не найдётся — коллекция
пуста, любой кейс отвечает 503. Тест `test_наклейки_каталог_внутри_api`
держит это место.

Запуск:
    python3 tools/fetch_stickers.py                 # скачать и собрать
    python3 tools/fetch_stickers.py --cache /tmp/x  # исходники брать/класть сюда
    python3 tools/fetch_stickers.py --offline       # только из кэша, без сети
    python3 tools/fetch_stickers.py --prune         # удалить лишние файлы в выходе
    python3 tools/fetch_stickers.py --catalog /tmp/c.json  # оглавление в другое место

Результат: web/public/stickers/<набор>/*.webp + api/data/stickers.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover — подсказка вместо трейсбека
    sys.exit("Нужен Pillow: api/.venv/bin/pip install pillow (или запускать api/.venv/bin/python)")

logger = logging.getLogger("stickers")

КОРЕНЬ = Path(__file__).resolve().parent.parent
ВЫХОД = КОРЕНЬ / "web" / "public" / "stickers"
КАТАЛОГ = КОРЕНЬ / "api" / "data" / "stickers.json"
КЭШ = КОРЕНЬ / ".cache" / "stickers-src"
CDN = "https://cdn.stickers.gg/stickers/{id}.png"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"

РЕДКОСТИ = ("common", "rare", "epic", "legend")


def коротко(p: Path) -> str:
    """Путь относительно корня репозитория для логов; чужой путь — как есть."""
    try:
        return str(p.relative_to(КОРЕНЬ))
    except ValueError:
        return str(p)


@dataclass(frozen=True)
class Набор:
    code: str
    title: str
    #: Страница пака на stickers.gg — источник, чтобы через год было ясно, откуда файлы.
    source: str


@dataclass(frozen=True)
class Исходник:
    #: Имя файла на CDN без расширения (например `1911-keroppi`).
    id: str
    #: Код наклейки — латиница, дефисы; это и имя файла, и значение в базе.
    code: str
    title: str
    rarity: str


НАБОРЫ: dict[Набор, tuple[Исходник, ...]] = {
    Набор("keropi", "Керопи", "https://stickers.gg/pack/5176-keropi"): (
        Исходник("1911-keroppi", "keropi-desk", "Керопи за уроками", "common"),
        Исходник("7769-keroppi", "keropi-bike", "Керопи на велике", "common"),
        Исходник("6868-keroppi", "keropi-shy", "Керопи смущён", "rare"),
        Исходник("9139-keroppi", "keropi-gogo", "Керопи: GO GO", "rare"),
        Исходник("4396-keroppi", "keropi-yes", "Керопи: YES!", "legend"),
    ),
    Набор("starrail", "Star Rail", "https://stickers.gg/pack/4087-star-rail"): (
        Исходник("1049-marchpoint", "march-point", "Март 7: вот так", "common"),
        Исходник("1245-marchcry", "march-cry", "Март 7 в слезах", "common"),
        Исходник("1824-marchproud", "march-proud", "Март 7 гордится", "common"),
        Исходник("1824-marchstare", "march-stare", "Март 7 смотрит", "common"),
        Исходник("3393-honkai", "march-thumbsup", "Март 7: класс!", "common"),
        Исходник("3826-honkai", "pompom-shock", "Пом-Пом в шоке", "common"),
        Исходник("4219-marchsnicker", "march-snicker", "Март 7 хихикает", "common"),
        Исходник("4734-marchglare", "march-glare", "Март 7 недовольна", "common"),
        Исходник("5215-marchpout", "march-pout", "Март 7 дуется", "common"),
        Исходник("6481-honkai", "stelle-question", "Стелла: что?", "common"),
        Исходник("7876-marchpic", "march-camera", "Март 7 фотографирует", "common"),
        Исходник("9533-honkai", "ghost-cry", "Призрак в слезах", "common"),
        Исходник("1990-marchcake", "march-cake", "Март 7 с тортом", "rare"),
        Исходник("3772-honkai", "pompom-music", "Пом-Пом напевает", "rare"),
        Исходник("4206-honkai", "pompom-peek", "Пом-Пом подглядывает", "rare"),
        Исходник("4952-marchcandy", "march-candy", "Март 7 с леденцом", "rare"),
        Исходник("4952-marchshop", "march-shop", "Март 7 на шопинге", "rare"),
        Исходник("5812-honkai", "facepalm", "Фейспалм", "rare"),
        Исходник("7349-honkai", "seele-angry", "Зеле злится", "rare"),
        Исходник("7738-marchhappy", "march-summer", "Март 7 на каникулах", "rare"),
        Исходник("8490-marchmegaphone", "march-megaphone", "Март 7 болеет за тебя", "rare"),
        Исходник("1922-honkai", "himeko-formulas", "Химеко за расчётами", "epic"),
        Исходник("3540-honkai", "seele-gun", "Зеле на прицеле", "epic"),
        Исходник("3811-honkai", "silverwolf-headphones", "Серебряный Волк в наушниках", "epic"),
        Исходник("7796-honkai", "bailu-treat", "Байлу с угощением", "epic"),
        Исходник("8946-honkai", "silverwolf-gum", "Серебряный Волк с жвачкой", "epic"),
        Исходник("4382-honkai", "clara-heart", "Клара с сердцем", "legend"),
        Исходник("9592-honkai", "seele-mic", "Зеле у микрофона", "legend"),
    ),
    Набор("halloween", "Хеллоуин", "https://stickers.gg/pack/3594-halloween"): (
        Исходник("2995-pepe-michael-myers", "pepe-myers", "Пепе-Майерс", "common"),
        Исходник("9603-pepe-jason", "pepe-jason", "Пепе-Джейсон", "common"),
        Исходник("2513-pepe-chucky", "pepe-chucky", "Пепе-Чаки", "rare"),
        Исходник("3405-pepe-freddy", "pepe-freddy", "Пепе-Фредди", "rare"),
        Исходник("3934-pepe-jigsaw-billy", "pepe-jigsaw", "Пепе-Пила", "epic"),
        Исходник("6458-pepe-pennywise", "pepe-pennywise", "Пепе-Пеннивайз", "legend"),
    ),
}


def проверить_каталог() -> None:
    """Дубли кодов и незнакомые редкости ловим до сети и до записи файлов."""
    коды: set[str] = set()
    for набор, исходники in НАБОРЫ.items():
        if not исходники:
            raise ValueError(f"Набор {набор.code} пуст")
        for и in исходники:
            if и.code in коды:
                raise ValueError(f"Дубль кода наклейки: {и.code}")
            if not и.code.replace("-", "").isalnum() or not и.code.isascii() or i_upper(и.code):
                raise ValueError(f"Код наклейки — латиница, цифры и дефисы: {и.code}")
            if и.rarity not in РЕДКОСТИ:
                raise ValueError(f"Незнакомая редкость {и.rarity!r} у {и.code}")
            коды.add(и.code)


def i_upper(s: str) -> bool:
    return s != s.lower()


def скачать(id: str, кэш: Path, набор: str, offline: bool) -> bytes:
    """Исходник берём из кэша; нет в кэше — качаем с CDN и кладём туда."""
    файл = кэш / набор / f"{id}.png"
    if файл.exists():
        return файл.read_bytes()
    if offline:
        raise FileNotFoundError(f"Нет в кэше и --offline: {файл}")
    url = CDN.format(id=id)
    logger.info(f"→ {url}")
    запрос = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/*,*/*"})
    try:
        with urllib.request.urlopen(запрос, timeout=60) as ответ:
            данные = ответ.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"CDN ответил {e.code} на {url}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise RuntimeError(f"Не достучались до {url}: {e}") from e
    if len(данные) < 1024:
        raise RuntimeError(f"Подозрительно маленький ответ ({len(данные)} байт): {url}")
    файл.parent.mkdir(parents=True, exist_ok=True)
    файл.write_bytes(данные)
    return данные


def подготовить(сырые: bytes, размер: int, порог_альфы: int, поле: float) -> Image.Image:
    """Один конвейер для всех: чистка альфы → обрезка → квадрат с полем → размер."""
    img = Image.open(BytesIO(сырые))
    img.load()
    img = img.convert("RGBA")

    # Дымка: полупрозрачные почти-белые пиксели по краям исходника. Порог
    # ниже любого честного края (антиалиасинг контура держит альфу выше 100).
    r, g, b, a = img.split()
    a = a.point(lambda v: 0 if v < порог_альфы else v)
    img = Image.merge("RGBA", (r, g, b, a))

    рамка = a.getbbox()
    if not рамка:
        raise ValueError("Картинка полностью прозрачна")
    img = img.crop(рамка)

    # Квадрат по большей стороне плюс поле — значок в анкете одного размера
    # у всех, а хвост или шляпа не упираются в край.
    сторона = int(max(img.size) * (1 + 2 * поле))
    холст = Image.new("RGBA", (сторона, сторона), (0, 0, 0, 0))
    холст.paste(img, ((сторона - img.width) // 2, (сторона - img.height) // 2))

    # Уменьшаем только вниз: растягивать 320-пиксельный исходник до 512 —
    # мыло вместо линий.
    цель = min(размер, сторона)
    return холст.resize((цель, цель), Image.Resampling.LANCZOS)


def собрать(args: argparse.Namespace) -> int:
    проверить_каталог()
    выход: Path = args.out
    выход.mkdir(parents=True, exist_ok=True)

    оглавление: list[dict[str, str]] = []
    ожидаемые: set[Path] = set()
    ошибки = 0
    for набор, исходники in НАБОРЫ.items():
        папка = выход / набор.code
        папка.mkdir(exist_ok=True)
        for и in исходники:
            файл = папка / f"{и.code}.webp"
            ожидаемые.add(файл)
            try:
                сырые = скачать(и.id, args.cache, набор.code, args.offline)
                картинка = подготовить(сырые, args.size, args.alpha_threshold, args.margin)
                картинка.save(файл, "WEBP", quality=args.quality, method=6)
                logger.debug(f"{коротко(файл)}: {картинка.width}px, {файл.stat().st_size // 1024} КБ")
            except Exception as e:
                ошибки += 1
                logger.error(f"{набор.code}/{и.code} ({и.id}): {e}")
                continue
            оглавление.append({"code": и.code, "title": и.title, "rarity": и.rarity, "set": набор.code})

    if ошибки:
        logger.error(f"Оглавление не записано: {ошибки} наклеек не собрались")
        return 1

    # Оглавление — в api/, а не в выход с картинками: см. шапку файла.
    каталог: Path = args.catalog
    каталог.parent.mkdir(parents=True, exist_ok=True)
    каталог.write_text(json.dumps(оглавление, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    лишние = [p for p in выход.rglob("*") if p.is_file() and p not in ожидаемые]
    if лишние:
        if args.prune:
            for p in лишние:
                p.unlink()
            for d in sorted((d for d in выход.rglob("*") if d.is_dir()), reverse=True):
                if not any(d.iterdir()):
                    d.rmdir()
            logger.info(f"Удалено лишних файлов: {len(лишние)}")
        else:
            logger.warning(f"В {выход} лежат {len(лишние)} файлов не из каталога — запустите с --prune")

    всего = sum(len(и) for и in НАБОРЫ.values())
    размер_кб = sum(p.stat().st_size for p in ожидаемые if p.suffix == ".webp") // 1024
    for набор, исходники in НАБОРЫ.items():
        по_р = {р: sum(1 for и in исходники if и.rarity == р) for р in РЕДКОСТИ}
        logger.info(f"{набор.title}: {len(исходники)} наклеек, " + ", ".join(f"{р} {n}" for р, n in по_р.items() if n))
    logger.info(
        f"Готово: {всего} наклеек в {len(НАБОРЫ)} наборах, {размер_кб} КБ, {коротко(выход)}; "
        f"оглавление {коротко(каталог)}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=ВЫХОД, help=f"куда писать картинки (по умолчанию {коротко(ВЫХОД)})")
    p.add_argument(
        "--catalog", type=Path, default=КАТАЛОГ, help=f"куда писать оглавление (по умолчанию {коротко(КАТАЛОГ)})"
    )
    p.add_argument("--cache", type=Path, default=КЭШ, help="кэш исходников <кэш>/<набор>/<id>.png")
    p.add_argument("--offline", action="store_true", help="не ходить в сеть, только кэш")
    p.add_argument("--prune", action="store_true", help="удалить в выходе файлы не из каталога")
    p.add_argument("--size", type=int, default=256, help="сторона квадрата, px (по умолчанию 256)")
    p.add_argument("--quality", type=int, default=88, help="качество WebP 1–100 (по умолчанию 88)")
    p.add_argument("--alpha-threshold", type=int, default=56, help="альфа ниже порога обнуляется (по умолчанию 56)")
    p.add_argument("--margin", type=float, default=0.04, help="поле вокруг персонажа, доля стороны (0.04)")
    p.add_argument("-v", "--verbose", action="store_true", help="подробный вывод")
    args = p.parse_args(argv)

    if not 1 <= args.quality <= 100:
        p.error("--quality в пределах 1–100")
    if not 0 <= args.alpha_threshold <= 255:
        p.error("--alpha-threshold в пределах 0–255")
    if args.size < 32:
        p.error("--size не меньше 32")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    # Pillow в DEBUG печатает каждый чанк PNG — шум, за которым не видно своих строк.
    logging.getLogger("PIL").setLevel(logging.WARNING)
    try:
        return собрать(args)
    except (ValueError, OSError) as e:
        logger.error(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
