/**
 * Ссылки на документы обязаны открываться из каждого клиента.
 *
 * Раньше они были относительными (`/terms.html`, `${window.location.origin}` в
 * профиле), и в нативной сборке это тупик: origin там `capacitor://localhost`
 * (`iosScheme` не задан намеренно), `@capacitor/browser` не-http отбрасывает,
 * системе схему `capacitor` открывать нечем. Нажатие не делало ничего — в том
 * числе на экране согласия, где человека просят принять условия и политику, и на
 * экране, который открывает ревью App Store.
 *
 * Ниже проверяется сам выбор базы (нативный случай через `window.location` не
 * проверить — он `[Unforgeable]` в jsdom), совпадение с каноническими адресами
 * лендинга и то, что страницы больше не зашивают путь напрямую.
 */

import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, it, expect } from "vitest";
import { LEGAL_ORIGIN, legalOrigin, legalUrl, выбратьБазу, type LegalPage } from "../legal";

const ДОКУМЕНТЫ: LegalPage[] = ["privacy", "terms", "guidelines", "moderation", "support"];

/** Страницы, с которых человек уходит читать документы. */
const СТРАНИЦЫ = ["Login.tsx", "Onboarding.tsx", "Profile.tsx"];

function прочитать(относительный: string): string {
  return fs.readFileSync(fileURLToPath(new URL(относительный, import.meta.url)), "utf8");
}

/**
 * Комментарии выкидываем: в них адреса упомянуты нарочно — там объясняется, что
 * именно было сломано. Искать поломку надо в коде.
 */
function без_комментариев(код: string): string {
  return код.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^[ \t]*\/\/.*$/gm, "");
}

describe("выбор базы для юридических документов", () => {
  it("нативную схему заменяет каноническим доменом, а не отдаёт как есть", () => {
    // Именно этот origin отдаёт WKWebView в собранном .ipa
    expect(выбратьБазу("", "capacitor://localhost")).toBe("https://simp.app");
    expect(выбратьБазу("", "capacitor://localhost")).not.toContain("capacitor");
  });

  it("в вебе оставляет текущий origin — там страницы лежат рядом", () => {
    // web/public синхронизируется с landing/ (scripts/sync-landing.mjs), поэтому
    // мини-апп и сайт обязаны отдавать свои копии, а не уводить на другой домен
    expect(выбратьБазу("", "https://simp.app")).toBe("https://simp.app");
    expect(выбратьБазу("", "http://localhost:5173")).toBe("http://localhost:5173");
  });

  it("не склеивает двойной слэш из origin с хвостом", () => {
    expect(выбратьБазу("", "https://simp.app/")).toBe("https://simp.app");
    expect(выбратьБазу("https://simp.app///", "")).toBe("https://simp.app");
  });

  it("настройку сборки ставит выше origin", () => {
    expect(выбратьБазу("https://staging.simp.app", "https://simp.app")).toBe(
      "https://staging.simp.app"
    );
    // Пробелы вокруг значения переменной окружения — обычное дело в .env
    expect(выбратьБазу("  https://staging.simp.app  ", "")).toBe("https://staging.simp.app");
  });

  it("непригодную настройку игнорирует, а не отдаёт неоткрываемый адрес", () => {
    // Сюда попадает и пустая переменная, и мусор, и та же нативная схема
    for (const мусор of ["", "   ", "simp.app", "capacitor://localhost", "file:///app"]) {
      expect(выбратьБазу(мусор, "")).toBe(LEGAL_ORIGIN);
    }
  });

  it("без окна вообще возвращает канонический домен", () => {
    expect(выбратьБазу("", "")).toBe(LEGAL_ORIGIN);
  });
});

describe("legalUrl", () => {
  it("всегда отдаёт абсолютный http(s)-адрес", () => {
    for (const документ of ДОКУМЕНТЫ) {
      const адрес = legalUrl(документ);
      expect(адрес, `${документ}: адрес открывается системным браузером только по http(s)`)
        .toMatch(/^https?:\/\//);
      expect(адрес).toBe(`${legalOrigin()}/${документ}.html`);
    }
  });

  it("совпадает с каноническими адресами лендинга", () => {
    // Домен и имена файлов берутся не из головы: они прописаны в самих
    // документах (rel="canonical") и в sitemap лендинга. Если домен разъедется,
    // бот и приложение начнут вести на чужой сайт — так уже было с souldawn.app.
    for (const документ of ДОКУМЕНТЫ) {
      const страница = прочитать(`../../../../landing/${документ}.html`);
      const канонический = страница.match(/<link rel="canonical" href="([^"]+)">/)?.[1];
      expect(канонический, `landing/${документ}.html не объявляет canonical`).toBeTruthy();
      expect(`${LEGAL_ORIGIN}/${документ}.html`).toBe(канонический);
    }
  });
});

describe("страницы с ссылками на документы", () => {
  it("не зашивают путь к документу мимо legalUrl", () => {
    for (const имя of СТРАНИЦЫ) {
      const код = без_комментариев(прочитать(`../../pages/${имя}`));
      const зашитые = [...код.matchAll(/["'`/]((?:privacy|terms|guidelines|moderation|support)\.html)/g)];
      expect(
        зашитые.map((m) => m[1]),
        `${имя}: адрес документа собран вручную — в нативной сборке он ` +
          `развернётся от capacitor://localhost и ссылка окажется мёртвой`
      ).toEqual([]);
      expect(код, `${имя}: ссылки на документы должны идти через legalUrl`).toContain("legalUrl(");
    }
  });

  it("не берут origin приложения как базу для документов", () => {
    for (const имя of СТРАНИЦЫ) {
      const код = без_комментариев(прочитать(`../../pages/${имя}`));
      expect(
        код,
        `${имя}: window.location.origin в нативной сборке — capacitor://localhost`
      ).not.toContain("window.location.origin");
    }
  });
});
