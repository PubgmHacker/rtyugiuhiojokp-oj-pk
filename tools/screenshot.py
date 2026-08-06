#!/usr/bin/env python3
"""Снимки экранов мини-аппа в настоящем мобильном вьюпорте.

Зачем отдельный инструмент: `chrome --headless --window-size=320,844` НЕ даёт
вьюпорт 320 — страница видит ~500px, и вёрстка выглядит обрезанной там, где
всё в порядке. Я на это уже попался и час искал несуществующий баг. Настоящий
мобильный вьюпорт получается только через `Emulation.setDeviceMetricsOverride`
по протоколу CDP, что здесь и делается.

Заодно инструмент честно докладывает, что вылезает за экран: по скриншоту это
видно не всегда, а числа не врут.

Запуск:
    cd web && npm run build && npx vite preview --port 4180 &
    python3 tools/screenshot.py /login /discover /profile

Результат: PNG в /tmp/souldawn-shots/ + список элементов, выходящих за вьюпорт.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ПОРТ_ОТЛАДКИ = 9333
БАЗА = "http://localhost:4180"
ВЫХОД = Path("/tmp/souldawn-shots")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

#: Ширины, на которых продукт обязан выглядеть целым. 320 — iPhone SE, самый
#: узкий живой экран; 390 — обычный iPhone; 430 — Pro Max.
ШИРИНЫ = (320, 390, 430)

ЗАМЕР = """
JSON.stringify((() => {
  const d = document.documentElement;
  const вылезли = [...document.querySelectorAll('*')]
    .map(e => ({ e, r: e.getBoundingClientRect() }))
    .filter(x => x.r.width > 0 && (x.r.right > d.clientWidth + 1 || x.r.left < -1))
    .slice(0, 8)
    .map(x => ({
      тег: x.e.tagName,
      класс: (x.e.className || '').toString().slice(0, 60),
      right: Math.round(x.r.right),
    }));
  return { вьюпорт: d.clientWidth, ширина_прокрутки: d.scrollWidth, вылезли };
})())
"""


def _соединиться():
    import websocket  # ставится отдельно: нужен только этому инструменту

    список = json.load(
        urllib.request.urlopen(f"http://localhost:{ПОРТ_ОТЛАДКИ}/json/list")
    )
    url = next(t["webSocketDebuggerUrl"] for t in список if t.get("type") == "page")
    return websocket.create_connection(url, timeout=20)


class Браузер:
    def __init__(self):
        self.процесс = subprocess.Popen(
            [
                CHROME, "--headless", "--disable-gpu",
                f"--remote-debugging-port={ПОРТ_ОТЛАДКИ}",
                "--remote-allow-origins=*", "about:blank",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        # Ждём, пока поднимется протокол: без этого первый запрос отвалится
        for _ in range(30):
            time.sleep(0.4)
            try:
                self.ws = _соединиться()
                break
            except Exception:
                continue
        else:
            raise RuntimeError("Chrome не поднял отладочный протокол")
        self._счёт = 0

    def зов(self, метод: str, params: dict | None = None) -> dict:
        self._счёт += 1
        мой = self._счёт
        self.ws.send(json.dumps({"id": мой, "method": метод, "params": params or {}}))
        while True:
            ответ = json.loads(self.ws.recv())
            if ответ.get("id") == мой:
                return ответ.get("result", {})

    def войти(self) -> None:
        """Положить фиктивную сессию, чтобы дойти до защищённых экранов.

        Без неё всё, кроме /login, редиректит на вход, и посмотреть на дека,
        профиль или коллекцию нельзя. Токен фиктивный: API в этом режиме не
        отвечает, зато видна сама вёрстка, скелетоны и пустые состояния —
        то, что и надо проверять глазами.
        """
        self.зов("Page.navigate", {"url": f"{БАЗА}/login"})
        time.sleep(2)
        self.зов("Runtime.evaluate", {"expression": """
            localStorage.setItem('sd_token', 'снимок-экрана');
            localStorage.setItem('sd_user', JSON.stringify({
              id: 'снимок', display_name: 'Аня', photos: [], interests: [],
              bio: '', gender: 'female', city: 'Москва', looking_for: 'any',
              is_incognito: false
            }));
        """})

    def снять(self, путь: str, ширина: int) -> dict:
        self.зов("Emulation.setDeviceMetricsOverride", {
            "width": ширина, "height": 844, "deviceScaleFactor": 2, "mobile": True,
        })
        self.зов("Page.navigate", {"url": f"{БАЗА}{путь}"})
        # Ждём отрисовки: анимации входа занимают до полусекунды
        time.sleep(3.5)

        замер = json.loads(
            self.зов("Runtime.evaluate", {"expression": ЗАМЕР, "returnByValue": True})
            ["result"]["value"]
        )
        снимок = self.зов("Page.captureScreenshot", {})
        имя = ВЫХОД / f"{путь.strip('/').replace('/', '_') or 'root'}-{ширина}.png"
        имя.write_bytes(base64.b64decode(снимок["data"]))
        замер["файл"] = str(имя)
        return замер

    def закрыть(self):
        try:
            self.ws.close()
        finally:
            self.процесс.terminate()


def main() -> int:
    пути = sys.argv[1:] or ["/login"]
    ВЫХОД.mkdir(parents=True, exist_ok=True)

    браузер = Браузер()
    плохо = 0
    try:
        браузер.войти()
        for путь in пути:
            for ширина in ШИРИНЫ:
                з = браузер.снять(путь, ширина)
                метка = "ок  "
                if з["вылезли"] or з["ширина_прокрутки"] > з["вьюпорт"] + 1:
                    метка = "ШИРЕ"
                    плохо += 1
                print(f"{метка} {путь:22} {ширина}px  {з['файл']}")
                for э in з["вылезли"]:
                    print(f"       за экраном: {э['тег']} .{э['класс']} right={э['right']}")
    finally:
        браузер.закрыть()

    print(f"\nСнимки: {ВЫХОД}")
    return 1 if плохо else 0


if __name__ == "__main__":
    sys.exit(main())
