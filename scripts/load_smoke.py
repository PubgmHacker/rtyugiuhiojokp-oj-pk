"""Нагрузочный смоук: первая волна пользователей одним залпом.

Сценарий повторяет реальный запуск: N человек почти одновременно
регистрируются и проходят горячие пути первого входа — дека, бейджи,
список чатов, лайк, уведомления, повторный вход. Это НЕ бенчмарк
максимальной пропускной способности, а проверка, что под залпом:

* пул Postgres не исчерпывается и не таймаутит (connection.py);
* rate limiter не косит легитимных людей (лимиты по user_id);
* нет 5xx ни на одном горячем пути;
* латентности остаются в человеческих пределах.

Запуск (API должен слушать base-url, например docker compose up -d api):

    api/.venv/bin/python scripts/load_smoke.py --users 300 --concurrency 100

Каждому виртуальному пользователю выдаётся свой X-Forwarded-For из
10.0.0.0/8: при TRUSTED_PROXY_COUNT=1 (дефолт) API считает его адресом
клиента — как в проде, где волна приходит с тысяч разных IP. Без этого
лимит /api/auth/dev (10/час с адреса) срезал бы всё после десятого гостя,
и смоук мерил бы лимитер, а не сервис.

Коды выхода: 0 — порог пройден, 1 — есть 5xx или ошибок больше 1%,
2 — API не поднялся к дедлайну.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger("load_smoke")


@dataclass
class RouteStats:
    """Латентности и исходы по одному маршруту."""

    latencies_ms: list[float] = field(default_factory=list)
    ok: int = 0
    fail_4xx: int = 0
    fail_5xx: int = 0
    fail_net: int = 0

    def record(self, ms: float, status: int | None) -> None:
        self.latencies_ms.append(ms)
        if status is None:
            self.fail_net += 1
        elif status >= 500:
            self.fail_5xx += 1
        elif status >= 400:
            self.fail_4xx += 1
        else:
            self.ok += 1

    @property
    def total(self) -> int:
        return len(self.latencies_ms)

    def percentile(self, p: float) -> float:
        if not self.latencies_ms:
            return 0.0
        data = sorted(self.latencies_ms)
        k = max(0, min(len(data) - 1, round(p / 100 * (len(data) - 1))))
        return data[k]


class Collector:
    """Потокобезопасный (в рамках одного loop) сборщик метрик."""

    def __init__(self) -> None:
        self.routes: dict[str, RouteStats] = defaultdict(RouteStats)

    def record(self, route: str, ms: float, status: int | None) -> None:
        self.routes[route].record(ms, status)


async def _call(
    client: httpx.AsyncClient,
    collector: Collector,
    route: str,
    method: str,
    url: str,
    **kwargs,
) -> httpx.Response | None:
    """Один вызов с записью метрики. Сетевые ошибки не роняют сценарий:
    для смоука упавший запрос — результат, который надо посчитать."""
    start = time.perf_counter()
    try:
        resp = await client.request(method, url, **kwargs)
    except httpx.HTTPError as e:
        collector.record(route, (time.perf_counter() - start) * 1000, None)
        logger.debug("%s %s: %s", method, url, e)
        return None
    collector.record(route, (time.perf_counter() - start) * 1000, resp.status_code)
    return resp


async def _user_journey(
    i: int,
    client: httpx.AsyncClient,
    collector: Collector,
    semaphore: asyncio.Semaphore,
    base: str,
) -> None:
    """Путь одного пользователя первой волны."""
    async with semaphore:
        # Свой «внешний» адрес: волна приходит с разных IP (см. докстринг)
        headers = {"X-Forwarded-For": f"10.{(i >> 16) & 255}.{(i >> 8) & 255}.{i & 255}"}

        resp = await _call(
            client, collector, "POST /auth/dev", "POST", f"{base}/api/auth/dev",
            json={"device_id": f"load-{i}", "name": f"Гость {i}"},
            headers=headers,
        )
        if resp is None or resp.status_code != 200:
            return
        try:
            token = resp.json().get("token", "")
        except json.JSONDecodeError:
            return
        if not token:
            return
        headers["Authorization"] = f"Bearer {token}"

        # Профиль: пол и предпочтения, чтобы дека не была пустой у всех
        await _call(
            client, collector, "PATCH /profiles/me", "PATCH",
            f"{base}/api/profiles/me",
            json={
                "display_name": f"Гость {i}",
                "bio": "Смоук первой волны",
                "city": "Москва",
                "gender": "male" if i % 2 else "female",
                "looking_for": "female" if i % 2 else "male",
                "birth_date": f"199{i % 10}-06-15",
            },
            headers=headers,
        )

        # Горячие пути первого входа
        deck_resp = await _call(
            client, collector, "GET /profiles/deck", "GET",
            f"{base}/api/profiles/deck", headers=headers,
        )
        await _call(client, collector, "GET /badges", "GET", f"{base}/api/badges", headers=headers)
        await _call(client, collector, "GET /matches", "GET", f"{base}/api/matches", headers=headers)
        await _call(
            client, collector, "GET /notifications", "GET",
            f"{base}/api/notifications", headers=headers,
        )

        # Лайк первому из деки: рождает мэтчи, стрики и события Redis
        if deck_resp is not None and deck_resp.status_code == 200:
            try:
                deck = deck_resp.json()
            except json.JSONDecodeError:
                deck = []
            if deck:
                await _call(
                    client, collector, "POST /likes", "POST", f"{base}/api/likes",
                    json={"target_id": deck[0]["id"], "type": "like"},
                    headers=headers,
                )

        # Повторный вход: то, что дергается на каждое открытие приложения
        await _call(client, collector, "GET /profiles/me", "GET", f"{base}/api/profiles/me", headers=headers)
        await _call(client, collector, "GET /matches (2й)", "GET", f"{base}/api/matches", headers=headers)


async def _wait_health(base: str, deadline_s: float) -> bool:
    """Ждать /health до дедлайна — compose поднимает API не мгновенно."""
    limit = time.monotonic() + deadline_s
    async with httpx.AsyncClient(timeout=3.0) as client:
        while time.monotonic() < limit:
            try:
                resp = await client.get(f"{base}/health")
                if resp.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1.0)
    return False


async def run(args: argparse.Namespace) -> int:
    base = args.base_url.rstrip("/")
    logger.info("Жду /health на %s (до %.0fс)…", base, args.health_deadline)
    if not await _wait_health(base, args.health_deadline):
        logger.error("API не поднялся к дедлайну — смоук не запускался")
        return 2

    collector = Collector()
    semaphore = asyncio.Semaphore(args.concurrency)
    limits = httpx.Limits(
        max_connections=args.concurrency, max_keepalive_connections=args.concurrency
    )
    timeout = httpx.Timeout(args.timeout, connect=5.0)

    logger.info(
        "Залп: %d пользователей, конкурентность %d, таймаут %.0fс",
        args.users, args.concurrency, args.timeout,
    )
    start = time.monotonic()
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        await asyncio.gather(*(
            _user_journey(i, client, collector, semaphore, base)
            for i in range(args.users)
        ))
    elapsed = time.monotonic() - start

    total = sum(s.total for s in collector.routes.values())
    total_5xx = sum(s.fail_5xx for s in collector.routes.values())
    total_net = sum(s.fail_net for s in collector.routes.values())
    total_4xx = sum(s.fail_4xx for s in collector.routes.values())

    print()
    print(f"{'Маршрут':<22} {'зап.':>5} {'ok':>5} {'4xx':>4} {'5xx':>4} {'сеть':>4} "
          f"{'p50 мс':>8} {'p95 мс':>8} {'max мс':>8}")
    for route in sorted(collector.routes):
        s = collector.routes[route]
        print(f"{route:<22} {s.total:>5} {s.ok:>5} {s.fail_4xx:>4} {s.fail_5xx:>4} "
              f"{s.fail_net:>4} {s.percentile(50):>8.0f} {s.percentile(95):>8.0f} "
              f"{max(s.latencies_ms or [0]):>8.0f}")

    all_lat = [ms for s in collector.routes.values() for ms in s.latencies_ms]
    print()
    print(f"Итого: {total} запросов за {elapsed:.1f}с "
          f"({total / elapsed:.0f} rps), медиана {statistics.median(all_lat or [0]):.0f} мс")
    print(f"Ошибки: 5xx={total_5xx}, сеть={total_net}, 4xx={total_4xx}")

    # Порог: любой 5xx — провал; сетевые ошибки свыше 1% — провал.
    # 4xx порогом не считаем: квоты и лимиты на части путей штатны,
    # но в отчёте они видны и оцениваются глазами.
    hard_failures = total_5xx + total_net
    if total_5xx > 0 or (total and hard_failures / total > 0.01):
        print("ПРОВАЛ: сервис не готов к залпу этой величины")
        return 1
    print("ПОРОГ ПРОЙДЕН: 5xx нет, сетевых ошибок меньше 1%")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--users", type=int, default=300, help="размер волны")
    parser.add_argument("--concurrency", type=int, default=100,
                        help="одновременных пользователей")
    parser.add_argument("--timeout", type=float, default=15.0,
                        help="таймаут одного запроса, с")
    parser.add_argument("--health-deadline", type=float, default=120.0,
                        help="сколько ждать /health, с")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
