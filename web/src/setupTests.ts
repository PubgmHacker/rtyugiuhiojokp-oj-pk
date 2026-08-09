/**
 * jsdom не реализует scrollIntoView — экраны чатов вызывают его при каждом
 * новом сообщении, без заглушки любой такой тест падает не из-за бага,
 * а из-за отсутствия DOM API в среде тестов.
 */
import "@testing-library/jest-dom/vitest";

if (!("scrollIntoView" in Element.prototype)) {
  (Element.prototype as { scrollIntoView: () => void }).scrollIntoView =
    function scrollIntoView() {};
}

/**
 * Node 26 объявляет свой глобальный `localStorage`, и без флага
 * `--localstorage-file` его геттер возвращает `undefined`. Этот геттер
 * перекрывает хранилище jsdom, поэтому `localStorage.getItem` падает с
 * TypeError ещё на импорте модуля — так у нас молча перестали запускаться
 * два файла тестов, включая проверку главного платного гейта: файл не
 * загружался, а «2 failed» читалось как чужая проблема среды.
 *
 * Ставим своё хранилище в памяти, только если настоящего в среде нет: под
 * браузером и в будущих версиях Node подменять родное не нужно.
 */
function поставить_хранилище(имя: "localStorage" | "sessionStorage") {
  const g = globalThis as Record<string, unknown>;
  try {
    if ((g[имя] as Storage | undefined)?.getItem) return;
  } catch {
    // Родной геттер может и бросать — значит хранилища всё равно нет
  }

  const данные = new Map<string, string>();
  const хранилище: Storage = {
    get length() {
      return данные.size;
    },
    key: (i) => [...данные.keys()][i] ?? null,
    getItem: (k) => данные.get(String(k)) ?? null,
    setItem: (k, v) => void данные.set(String(k), String(v)),
    removeItem: (k) => void данные.delete(String(k)),
    clear: () => данные.clear(),
  };
  Object.defineProperty(g, имя, {
    value: хранилище,
    configurable: true,
    writable: true,
  });
}

поставить_хранилище("localStorage");
поставить_хранилище("sessionStorage");
