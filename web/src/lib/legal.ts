/**
 * Адреса юридических документов — политики, оферты, правил, поддержки.
 *
 * Почему это не относительная ссылка. В нативной сборке страница приложения
 * открыта не по http: `web/capacitor.config.ts` намеренно не задаёт `iosScheme`
 * (иначе WKWebView перехватывает https и ассеты уходят в сеть с -1003), поэтому
 * `window.location.origin` там — `capacitor://localhost`. Дальше ломается всё:
 * `@capacitor/browser` отбрасывает любую схему кроме http/https
 * («Unable to display URL»), запасной `window.open` отдаёт тот же адрес в
 * `UIApplication.shared.open`, а системе схему `capacitor` открывать нечем —
 * в Info.plist нет CFBundleURLTypes. Кнопка нажимается и не делает ничего.
 * Ровно та же беда у `<a href="/terms.html" target="_blank">`: пустой
 * targetFrame уводит переход в `createWebViewWith`, оттуда в
 * `UIApplication.shared.open` — и снова тишина.
 *
 * Тишина здесь дороже обычной: на эти две ссылки человек жмёт на экране
 * согласия, когда его просят принять то, что он не может прочитать.
 *
 * Порядок выбора базы:
 *   1. `VITE_SITE_URL` — явная настройка сборки, ей верим;
 *   2. текущий origin, если он http(s) — веб и Telegram Mini App отдают свои же
 *      копии страниц (они лежат в `web/public`, синхронизируются с `landing/`);
 *   3. `https://simp.app` — канонический домен из APPSTORE.md и sitemap
 *      лендинга. Сюда попадает нативная сборка.
 */

/** Документы, которые обязаны открываться из любого клиента. */
export type LegalPage = "privacy" | "terms" | "guidelines" | "moderation" | "support";

/**
 * Канонический домен документов: он же в APPSTORE.md (Privacy Policy URL,
 * Terms of Use), в `<link rel="canonical">` лендинга и в его sitemap.
 */
export const LEGAL_ORIGIN = "https://simp.app";

/**
 * Адрес поддержки. Он же в подвале лендинга и в правилах сообщества.
 * Держим одной константой: по нему человек оспаривает блокировку, и
 * разошедшийся адрес означает жалобу, которая никуда не пришла.
 */
export const SUPPORT_EMAIL = "support@simp.app";

const НАСТРОЙКА = String(import.meta.env.VITE_SITE_URL ?? "").trim();

/** Годится ли база для внешнего открытия: только http и https маршрутизируются. */
function пригодна(база: string): boolean {
  return /^https?:\/\/\S/i.test(база);
}

function без_хвоста(база: string): string {
  return база.replace(/\/+$/, "");
}

/**
 * Выбор базы из того, что известно сборке и рантайму. Вынесено отдельно от
 * `legalOrigin`, потому что вся суть починки — в этом выборе, а `window.location`
 * в jsdom неподменяем (`[Unforgeable]` по спецификации), и через него нативный
 * случай не проверить.
 */
export function выбратьБазу(настройка: string, origin: string): string {
  const явная = настройка.trim();
  if (пригодна(явная)) return без_хвоста(явная);
  if (пригодна(origin)) return без_хвоста(origin);
  return LEGAL_ORIGIN;
}

/** База, от которой считаются адреса документов в текущей сборке. */
export function legalOrigin(): string {
  // Origin читаем при вызове, а не при загрузке модуля: бандл один и тот же для
  // веба и для нативной обёртки, различает их только рантайм.
  const origin = typeof window === "undefined" ? "" : window.location?.origin || "";
  return выбратьБазу(НАСТРОЙКА, origin);
}

/**
 * Абсолютный адрес документа. Открывать через `openExternal` или обычной
 * ссылкой — оба пути в нативной сборке уходят в системный браузер, и оба
 * требуют http(s).
 */
export function legalUrl(page: LegalPage): string {
  return `${legalOrigin()}/${page}.html`;
}
