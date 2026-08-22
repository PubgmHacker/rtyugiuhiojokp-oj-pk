/**
 * Язык интерфейса мини-аппа.
 *
 * Бот спрашивает язык первым же экраном после /start, и до колонки
 * `dating_users.locale` (миграция a1e6f30c74d2) ответ выбрасывался: он жил в
 * FSM-состоянии, которого у мини-аппа нет вовсе. Человек выбирал узбекский и
 * открывал приложение на русском. Здесь — сторона клиента: язык приезжает в
 * профиле (`UserProfile.locale`, кладётся уже в ответ на вход — специально,
 * чтобы не мигнуть русским до первого запроса анкеты) и отсюда управляет
 * `<html lang>`, форматом дат и переводами.
 *
 * ЧЕСТНЫЙ ОБЪЁМ ПЕРЕВОДА. Переведено то, что ниже в `СЛОВАРЬ`: оболочка,
 * навигация, экран входа и сам выбор языка. Остальные экраны пока по-русски —
 * в приложении около 700 строк текста, и машинный перевод их на семь языков
 * даёт хуже, чем русский: в дейтинге текст читают внимательно. Ключи
 * добавляются по мере живого перевода, инфраструктура готова.
 *
 * `ru` и `en` обязаны быть у каждого ключа (это проверяет тест), остальные
 * пять падают в `en`, а не в русский: человек, выбравший турецкий, скорее
 * прочтёт английский. Та же политика, что у бота — см. комментарий над
 * `ONBOARDING_LANGUAGES` в bot/keyboards.py.
 */

import { useCallback, useEffect } from "react";
import { useStore } from "./store";

/**
 * Языки, ровно как в `api/services/locales.ЯЗЫКИ` и
 * `bot/texts.ONBOARDING_LOCALES`. Три копии в трёх деплоях — общего модуля
 * между ними быть не может, поэтому совпадение сторожит тест: разъедутся, и
 * мини-апп покажет язык, на который API ответит 422.
 */
export const ЯЗЫКИ = ["ru", "en", "uz", "es", "tr", "id", "zh"] as const;

export type Язык = (typeof ЯЗЫКИ)[number];

/** Как в `server_default` миграции и в `locales.ПО_УМОЛЧАНИЮ`. */
export const ПО_УМОЛЧАНИЮ: Язык = "ru";

/** Язык, в который падает непереведённый ключ. Английский, не русский. */
export const ФОЛБЭК_ПЕРЕВОДА: Язык = "en";

/**
 * Подписи для выбора языка — те же, что на клавиатуре бота
 * (`ONBOARDING_LANGUAGES`), чтобы человек узнал свой выбор. Названия на самих
 * языках и не переводятся: «Türkçe» остаётся «Türkçe» в любом интерфейсе, а
 * «турецкий» на незнакомом языке не читается вообще.
 */
export const НАЗВАНИЯ: Record<Язык, string> = {
  ru: "🇷🇺 Русский",
  en: "🇬🇧 English",
  uz: "🇺🇿 O'zbekcha",
  es: "🇪🇸 Español",
  tr: "🇹🇷 Türkçe",
  id: "🇮🇩 Bahasa Indonesia",
  zh: "🇨🇳 中文",
};

/**
 * Теги для `Intl`. Голый код работает, но региональный даёт правильный вид
 * даты: `en` — это «Aug 20», `en-GB` — «20 Aug», и второе ближе тому, кто
 * пришёл не из США. Для `zh` тег с письменностью важнее региона.
 */
const ТЕГИ: Record<Язык, string> = {
  ru: "ru-RU",
  en: "en-GB",
  uz: "uz-Latn-UZ",
  es: "es-ES",
  tr: "tr-TR",
  id: "id-ID",
  zh: "zh-Hans-CN",
};

/** Проверка кода без приведения типа на веру. */
export function поддерживается(код: unknown): код is Язык {
  return typeof код === "string" && (ЯЗЫКИ as readonly string[]).includes(код);
}

/**
 * Чтение сохранённого значения: мусор превращается в язык по умолчанию.
 *
 * Зеркало `locales.нормализовать` на сервере — и ровно так же не для ввода. На
 * запись язык проверяется схемой (`ProfileUpdate.locale`, 422 на неизвестный
 * код): тихая подстановка там дала бы клиенту право сказать «язык сохранён» и
 * соврать. А здесь падать поздно — значение уже в базе или в localStorage.
 */
export function нормализовать(код: unknown): Язык {
  if (typeof код !== "string") return ПО_УМОЛЧАНИЮ;
  const чистый = код.trim().toLowerCase();
  return поддерживается(чистый) ? чистый : ПО_УМОЛЧАНИЮ;
}

/**
 * Язык до входа — единственный случай, когда спросить некого.
 *
 * У пришедшего из Telegram язык уже выбран в боте и лежит в профиле, но вход
 * через Apple бота не касается вовсе (Guideline 4.8): для такого человека
 * настройка браузера — единственный сигнал, и она точнее, чем русский по
 * умолчанию. Берётся только основная часть тега: `tr-TR` → `tr`.
 */
export function изБраузера(): Язык {
  const список = typeof navigator === "undefined" ? [] : navigator.languages ?? [];
  const кандидаты = список.length ? список : [navigator?.language ?? ""];
  for (const тег of кандидаты) {
    const основа = String(тег).split("-")[0]?.toLowerCase();
    if (поддерживается(основа)) return основа;
  }
  return ПО_УМОЛЧАНИЮ;
}

/**
 * Считается один раз при загрузке модуля: `navigator.languages` не меняется
 * без перезагрузки страницы, а вызов на каждый рендер заставил бы React
 * сравнивать заново.
 */
const ЯЗЫК_БЕЗ_ПРОФИЛЯ = изБраузера();

/**
 * `<html lang>` — не косметика. От него зависят экранные читалки (иначе
 * турецкий текст читается английскими правилами и получается каша), переносы
 * слов и подбор шрифта для 中文.
 */
export function применитьКДокументу(язык: Язык): void {
  if (typeof document !== "undefined") document.documentElement.lang = язык;
}

// ── Словарь ─────────────────────────────────────────────────────
//
// Ключ первым, языки под ним: так вся строка видна целиком одним куском, а
// пропущенный перевод заметен глазом и тестом. Раскладка «язык → все ключи»
// прячет расхождения в конец файла.

type Перевод = { ru: string; en: string } & Partial<Record<Язык, string>>;

export const СЛОВАРЬ = {
  // Навигация: пять вкладок из `NAV_ITEMS`. Короткие ярлыки — их и переводим
  // на все семь: ошибиться тут негде, а видны они на каждом экране. Названия
  // главной вкладки взяты идиоматично, а не буквально: «Лента» в приложениях
  // этих языков зовётся «Главная», и буквальный перевод читался бы чужеродно.
  "nav.feed": {
    ru: "Лента",
    en: "Feed",
    uz: "Lenta",
    es: "Inicio",
    tr: "Akış",
    id: "Beranda",
    zh: "首页",
  },
  "nav.likes": {
    ru: "Лайки",
    en: "Likes",
    uz: "Layklar",
    es: "Me gusta",
    tr: "Beğeniler",
    id: "Suka",
    zh: "喜欢",
  },
  "nav.chats": {
    ru: "Чаты",
    en: "Chats",
    uz: "Chatlar",
    es: "Chats",
    tr: "Sohbetler",
    id: "Obrolan",
    zh: "聊天",
  },
  "nav.more": {
    ru: "Ещё",
    en: "More",
    uz: "Yana",
    es: "Más",
    tr: "Daha",
    id: "Lainnya",
    zh: "更多",
  },
  "nav.profile": {
    ru: "Профиль",
    en: "Profile",
    uz: "Profil",
    es: "Perfil",
    tr: "Profil",
    id: "Profil",
    zh: "我的",
  },
  // Название всей нижней панели — его читает вслух экранная читалка, и
  // по-русски оно бессмысленно для того, кто выбрал другой язык.
  "nav.aria": {
    ru: "Основная навигация",
    en: "Main navigation",
    uz: "Asosiy navigatsiya",
    es: "Navegación principal",
    tr: "Ana gezinme",
    id: "Navigasi utama",
    zh: "主导航",
  },

  // Выбор языка. Этот экран обязан читаться на всех семи: человек попадает
  // сюда именно потому, что интерфейс не на его языке, и русская подпись у
  // выхода — насмешка.
  "lang.title": {
    ru: "Язык",
    en: "Language",
    uz: "Til",
    es: "Idioma",
    tr: "Dil",
    id: "Bahasa",
    zh: "语言",
  },
  "lang.hint": {
    ru: "Язык интерфейса приложения и сообщений бота.",
    en: "Language of the app interface and bot messages.",
    uz: "Ilova interfeysi va bot xabarlari tili.",
    es: "Idioma de la interfaz y de los mensajes del bot.",
    tr: "Uygulama arayüzü ve bot mesajlarının dili.",
    id: "Bahasa antarmuka aplikasi dan pesan bot.",
    zh: "应用界面和机器人消息的语言。",
  },
  "lang.saved": {
    ru: "Язык сохранён",
    en: "Language saved",
    uz: "Til saqlandi",
    es: "Idioma guardado",
    tr: "Dil kaydedildi",
    id: "Bahasa disimpan",
    zh: "语言已保存",
  },
  // Текст честный: выбор не применён, а не «не удалось отправить». Человек
  // должен понять, что жать снова, а не что где-то уже сохранилось.
  "lang.failed": {
    ru: "Не удалось сменить язык. Попробуйте ещё раз",
    en: "Couldn't change the language. Please try again",
    uz: "Tilni almashtirib bo'lmadi. Yana urinib ko'ring",
    es: "No se pudo cambiar el idioma. Inténtalo de nuevo",
    tr: "Dil değiştirilemedi. Lütfen tekrar deneyin",
    id: "Gagal mengganti bahasa. Coba lagi",
    zh: "语言切换失败，请重试",
  },
  "lang.partial": {
    ru: "Часть экранов пока на русском — переводим.",
    en: "Some screens are still in Russian — translation in progress.",
    uz: "Ba'zi ekranlar hozircha rus tilida — tarjima qilinmoqda.",
    es: "Algunas pantallas siguen en ruso: la traducción está en curso.",
    tr: "Bazı ekranlar hâlâ Rusça — çeviri sürüyor.",
    id: "Sebagian layar masih berbahasa Rusia — sedang diterjemahkan.",
    zh: "部分页面仍为俄语，翻译中。",
  },

  // Общие подписи, которые встречаются на нескольких экранах.
  "common.save": {
    ru: "Сохранить",
    en: "Save",
    uz: "Saqlash",
    es: "Guardar",
    tr: "Kaydet",
    id: "Simpan",
    zh: "保存",
  },
  "common.cancel": {
    ru: "Отмена",
    en: "Cancel",
    uz: "Bekor qilish",
    es: "Cancelar",
    tr: "İptal",
    id: "Batal",
    zh: "取消",
  },
  "common.back": {
    ru: "Назад",
    en: "Back",
    uz: "Orqaga",
    es: "Atrás",
    tr: "Geri",
    id: "Kembali",
    zh: "返回",
  },
  "common.retry": {
    ru: "Повторить",
    en: "Retry",
    uz: "Qayta urinish",
    es: "Reintentar",
    tr: "Yeniden dene",
    id: "Coba lagi",
    zh: "重试",
  },
  "common.loading": {
    ru: "Загрузка…",
    en: "Loading…",
    uz: "Yuklanmoqda…",
    es: "Cargando…",
    tr: "Yükleniyor…",
    id: "Memuat…",
    zh: "加载中…",
  },

  // Даты. Без этих трёх ключей перевод даты выходил бы половинчатым: формат
  // локальный, а «Сегодня» рядом с ним — по-русски. Регистр разный намеренно:
  // в чате это заголовок дня (с большой), в списке чатов — подпись в строке.
  "date.today": {
    ru: "Сегодня",
    en: "Today",
    uz: "Bugun",
    es: "Hoy",
    tr: "Bugün",
    id: "Hari ini",
    zh: "今天",
  },
  "date.yesterday": {
    ru: "Вчера",
    en: "Yesterday",
    uz: "Kecha",
    es: "Ayer",
    tr: "Dün",
    id: "Kemarin",
    zh: "昨天",
  },
  "date.yesterdayShort": {
    ru: "вчера",
    en: "yesterday",
    uz: "kecha",
    es: "ayer",
    tr: "dün",
    id: "kemarin",
    zh: "昨天",
  },
  // Дата обнуления попыток неизвестна только при битом значении с сервера —
  // тогда честнее сказать «в начале месяца», чем показать «Invalid Date».
  "date.monthStart": {
    ru: "в начале месяца",
    en: "at the start of the month",
    uz: "oy boshida",
    es: "a principios de mes",
    tr: "ayın başında",
    id: "pada awal bulan",
    zh: "月初",
  },
  // Когда вернутся лайки — текст с лимитного экрана и закрытого чата. Фраза
  // переводится целиком, а не склеивается из куска и даты: в турецком и
  // китайском порядок другой, и «в» посередине оставило бы кашу.
  "slot.today": {
    ru: "сегодня в {time}",
    en: "today at {time}",
    uz: "bugun {time}da",
    es: "hoy a las {time}",
    tr: "bugün {time}",
    id: "hari ini pukul {time}",
    zh: "今天 {time}",
  },
  "slot.tomorrow": {
    ru: "завтра в {time}",
    en: "tomorrow at {time}",
    uz: "ertaga {time}da",
    es: "mañana a las {time}",
    tr: "yarın {time}",
    id: "besok pukul {time}",
    zh: "明天 {time}",
  },
  "slot.onDate": {
    ru: "{date} в {time}",
    en: "{date} at {time}",
    uz: "{date} {time}da",
    es: "{date} a las {time}",
    tr: "{date} {time}",
    id: "{date} pukul {time}",
    zh: "{date} {time}",
  },
  // Значение с сервера битое: точного срока не знаем. Обещать «сегодня»
  // нельзя — человек вернётся и не найдёт лайков.
  "slot.withinDay": {
    ru: "в течение суток",
    en: "within 24 hours",
    uz: "bir kun ichida",
    es: "en 24 horas",
    tr: "24 saat içinde",
    id: "dalam 24 jam",
    zh: "24 小时内",
  },
} satisfies Record<string, Перевод>;

export type Ключ = keyof typeof СЛОВАРЬ;

/**
 * Перевод по ключу. Никогда не возвращает пустую строку: непереведённый ключ
 * падает в английский, отсутствующий — отдаёт сам ключ. Пустой текст на
 * кнопке хуже английского и хуже даже `nav.likes`: кнопка выглядит сломанной,
 * и человек не понимает, куда нажал.
 *
 * Подстановки — `{имя}`. Склейка строк на месте вызова не годится: в турецком
 * и китайском порядок слов другой, и переводчику нужна вся фраза целиком.
 */
export function перевести(
  язык: Язык,
  ключ: Ключ,
  подстановки?: Record<string, string | number>,
): string {
  const строка: Перевод | undefined = СЛОВАРЬ[ключ];
  if (!строка) return ключ;
  const текст = строка[язык] ?? строка[ФОЛБЭК_ПЕРЕВОДА] ?? строка.ru ?? ключ;
  if (!подстановки) return текст;
  return текст.replace(/\{(\w+)\}/g, (целое, имя: string) =>
    имя in подстановки ? String(подстановки[имя]) : целое,
  );
}

// ── Даты и числа ────────────────────────────────────────────────
//
// Формат даты был зашит как "ru-RU" в одиннадцати местах. Для турка это не
// «неудобно», а нечитаемо: «20 авг.» кириллицей не разбирается вообще. Ниже
// один вход, берущий язык из аккаунта.

/** Кэш форматтеров: `Intl.DateTimeFormat` дорог, а в списке чатов он на строку. */
const форматтеры = new Map<string, Intl.DateTimeFormat>();

function форматтер(язык: Язык, опции: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const ключ = `${язык}|${JSON.stringify(опции)}`;
  let готовый = форматтеры.get(ключ);
  if (!готовый) {
    try {
      готовый = new Intl.DateTimeFormat(ТЕГИ[язык], опции);
    } catch {
      // Тег может быть не поддержан старым движком (`uz-Latn-UZ` в вебвью
      // древнего Android). Падать из-за подписи под сообщением нельзя.
      готовый = new Intl.DateTimeFormat(undefined, опции);
    }
    форматтеры.set(ключ, готовый);
  }
  return готовый;
}

/** Часы и минуты — подпись под сообщением. */
export function форматВремени(дата: Date, язык: Язык): string {
  return форматтер(язык, { hour: "2-digit", minute: "2-digit" }).format(дата);
}

/** «20 авг.» — короткая дата для списков. */
export function форматДаты(дата: Date, язык: Язык): string {
  return форматтер(язык, { day: "numeric", month: "short" }).format(дата);
}

/** «20 августа» — дата в тексте, где место есть. */
export function форматДатыПолной(дата: Date, язык: Язык): string {
  return форматтер(язык, { day: "numeric", month: "long" }).format(дата);
}

/**
 * Разделитель дня в переписке. Год — только чужой: «20 августа 2026» в
 * переписке этого года шум, а без года в переписке прошлого не понять, о каком
 * дне речь.
 */
export function форматДняРазделителя(дата: Date, язык: Язык, сГодом: boolean): string {
  return форматтер(язык, {
    day: "numeric",
    month: "long",
    ...(сГодом ? { year: "numeric" as const } : {}),
  }).format(дата);
}

/** Дата без времени — таблицы админки. */
export function форматКороткойДаты(дата: Date, язык: Язык): string {
  return форматтер(язык, { dateStyle: "short" }).format(дата);
}

/** Дата и время — журнал модерации, где важна минута. */
export function форматДатыВремени(дата: Date, язык: Язык): string {
  return форматтер(язык, { dateStyle: "short", timeStyle: "short" }).format(дата);
}

/** Разделители разрядов: 1 234 против 1,234. Счётчики в админке. */
export function форматЧисла(число: number, язык: Язык): string {
  try {
    return new Intl.NumberFormat(ТЕГИ[язык]).format(число);
  } catch {
    return new Intl.NumberFormat().format(число);
  }
}

// ── Хуки ────────────────────────────────────────────────────────

/**
 * Язык текущего человека.
 *
 * Источник один — профиль в store, который наполняется из localStorage
 * синхронно при загрузке модуля (см. `сохранённыйПрофиль`). Поэтому язык верен
 * уже на первом рендере: отдельного состояния для языка нет и разъехаться
 * нечему. Профиля нет только до входа — там настройка браузера.
 */
export function useЯзык(): Язык {
  const изПрофиля = useStore((s) => s.user?.locale);
  return изПрофиля ? нормализовать(изПрофиля) : ЯЗЫК_БЕЗ_ПРОФИЛЯ;
}

/** Перевод, привязанный к языку человека: `const t = useT(); t("nav.likes")`. */
export function useT(): (ключ: Ключ, подстановки?: Record<string, string | number>) => string {
  const язык = useЯзык();
  return useCallback(
    (ключ: Ключ, подстановки?: Record<string, string | number>) =>
      перевести(язык, ключ, подстановки),
    [язык],
  );
}

/**
 * Держит `<html lang>` в согласии с выбором. Вызывается один раз в корне
 * приложения — эффект в `useT` был бы побочным действием в хуке, который
 * вызывают десятки компонентов.
 */
export function useЯзыкДокумента(): Язык {
  const язык = useЯзык();
  useEffect(() => применитьКДокументу(язык), [язык]);
  return язык;
}
