"""Zhipu доступен с двух площадок — и обе должны работать без правок кода.

Материковая open.bigmodel.cn не регистрирует российские номера, поэтому
рабочий путь за ключом — международная Z.ai (регистрация по почте). Её ключ
ходит только через https://api.z.ai/api/paas/v4 и под другими именами
моделей, так что и адрес, и модели обязаны быть настройками, а не литералами
в коде. Дефолты — материковые: существующие ключи работают без правок.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from config import get_settings

КОРЕНЬ = Path(__file__).resolve().parents[2]
МАТЕРИК = "https://open.bigmodel.cn"
ZAI = "https://api.z.ai/api/paas/v4"

settings = get_settings()


@pytest.fixture
def _чистые_клиенты(monkeypatch):
    """Свежая фабрика клиентов: глобальные синглтоны сброшены, ключ задан.

    Без ключа фабрики честно возвращают None, а уже созданный клиент
    переживает monkeypatch настроек — для проверки адреса нужно и то, и то.
    """
    import services.ai_matchmaker as ai_matchmaker
    import services.ai_moderation as ai_moderation

    monkeypatch.setattr(ai_moderation, "_zhipu_client", None)
    monkeypatch.setattr(ai_matchmaker, "_zhipu_client", None)
    monkeypatch.setattr(settings, "ZHIPU_API_KEY", "sk-тестовый")
    return ai_moderation, ai_matchmaker


def test_без_адреса_клиент_смотрит_на_материк(_чистые_клиенты, monkeypatch):
    """Пустой ZHIPU_BASE_URL = дефолт SDK, а не пустая строка в httpx."""
    ai_moderation, ai_matchmaker = _чистые_клиенты
    monkeypatch.setattr(settings, "ZHIPU_BASE_URL", "")

    for модуль in (ai_moderation, ai_matchmaker):
        клиент = модуль._get_zhipu_client()
        assert клиент is not None
        assert str(клиент._base_url).startswith(МАТЕРИК)


def test_адрес_zai_подхватывается_обоими_клиентами(_чистые_клиенты, monkeypatch):
    """Обе фабрики api (модерация и мэтчер) уважают ZHIPU_BASE_URL."""
    ai_moderation, ai_matchmaker = _чистые_клиенты
    monkeypatch.setattr(settings, "ZHIPU_BASE_URL", ZAI)

    for модуль in (ai_moderation, ai_matchmaker):
        клиент = модуль._get_zhipu_client()
        assert клиент is not None
        assert str(клиент._base_url).startswith(ZAI)


def test_имена_моделей_нигде_не_зашиты():
    """Литерал `model="glm-…"` вне config — дорога назад к неработающему Z.ai.

    На Z.ai материковых имён нет: зашитый литерал означает 404 от площадки
    при верном ключе и адресе. Единственное место имён — дефолты настроек.
    """
    зашито: list[str] = []
    for папка in ("api", "bot"):
        for файл in (КОРЕНЬ / папка).rglob("*.py"):
            частями = файл.parts
            if ".venv" in частями or "tests" in частями:
                continue
            if файл.name == "config.py":
                continue
            for номер, строка in enumerate(файл.read_text().splitlines(), 1):
                if re.search(r"model\s*=\s*[\"']glm-", строка):
                    зашито.append(f"{файл.relative_to(КОРЕНЬ)}:{номер}")
    assert not зашито, (
        "имя модели зашито литералом, возьмите ZHIPU_TEXT_MODEL/ZHIPU_VISION_MODEL: "
        + ", ".join(зашито)
    )


def test_бот_тоже_настраивается_и_ставит_sdk():
    """Бот — отдельный сервис со своим образом, и у него своя пара граблей.

    Первая уже случалась: zhipuai не было в bot/requirements.txt, и
    фото-модерация в проде вечно отклоняла КАЖДОЕ фото (fail-closed) даже
    с заданным ключом. Вторая — половинчатая параметризация: адрес читается,
    а моделям оставлены литералы (или наоборот) — ключ Z.ai снова мёртв.
    """
    требования = (КОРЕНЬ / "bot" / "requirements.txt").read_text()
    assert re.search(r"^zhipuai", требования, re.M), (
        "в bot/requirements.txt нет zhipuai — фото-модерация бота "
        "в проде будет вечно fail-closed даже с ключом"
    )

    модерация = (КОРЕНЬ / "bot" / "services" / "moderation.py").read_text()
    for имя in ("ZHIPU_BASE_URL", "ZHIPU_TEXT_MODEL", "ZHIPU_VISION_MODEL"):
        assert имя in модерация, f"bot/services/moderation.py не использует {имя}"

    конфиг = (КОРЕНЬ / "bot" / "config.py").read_text()
    for дефолт in ('"glm-4-flash"', '"glm-4v-flash"'):
        assert дефолт in конфиг, (
            f"в bot/config.py пропал материковый дефолт {дефолт} — "
            "существующие ключи с open.bigmodel.cn перестанут работать"
        )
