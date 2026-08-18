/**
 * Черновик анкеты.
 *
 * Зачем: анкета — десять шагов, а живёт она внутри webview, который хост
 * выгружает без предупреждения. Telegram на iOS убивает мини-апп при
 * переключении чата, Safari — при нехватке памяти, нативная обёртка — при
 * сворачивании. Без черновика человек на восьмом шаге возвращается к «Как вас
 * зовут?», и второй раз до конца обычно не доходит: это самая дорогая потеря
 * из возможных, потому что она стоит на входе.
 *
 * Почему localStorage, а не сервер: половина анкеты не проходит валидацию
 * `PATCH /profiles/me` (обязательны имя, возраст, пол, город, фото), а
 * ослаблять схему ради черновика — значит пускать в базу нежизнеспособные
 * записи, которые потом попадут в подбор и в чужую деку. Фотографии
 * исключение: они загружаются сразу и живут в хранилище, поэтому в черновик
 * попадают уже готовыми ссылками.
 */

export interface OnboardingDraft {
  /** Версия формы. Не совпала — черновик выбрасываем, а не читаем по частям. */
  v: 1;
  /** Шаг, на котором человека прервали. */
  index: number;
  name: string;
  age: string;
  gender: string;
  lookingFor: string;
  city: string;
  coords: { lat: number; lon: number } | null;
  /** Только загруженные ссылки: слоты «в процессе» и «ошибка» смысла не имеют. */
  photos: string[];
  interests: string[];
  goal: string;
  relationType: string;
  subculture: string;
  mbti: string;
  height: string;
  bio: string;
  savedAt: number;
}

export type DraftFields = Omit<OnboardingDraft, "v" | "savedAt">;

const STORAGE_KEY = "sd_onboarding_draft";
const VERSION = 1 as const;

/**
 * Срок годности черновика.
 *
 * Неделя, а не бессрочно: город и «кого показывать» месячной давности хуже
 * пустого поля — человек уже переехал или передумал, а подставленный ответ
 * выглядит как чужой и вызывает недоверие к остальной анкете.
 */
const TTL_MS = 7 * 24 * 60 * 60 * 1000;

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((v) => typeof v === "string");
}

function isCoords(value: unknown): value is { lat: number; lon: number } | null {
  if (value === null) return true;
  if (typeof value !== "object" || value === null) return false;
  const c = value as Record<string, unknown>;
  return Number.isFinite(c.lat) && Number.isFinite(c.lon);
}

/**
 * Прочитать черновик.
 *
 * Любая несостоятельность — чужая версия, битый JSON, истёкший срок, не тот
 * тип поля — заканчивается удалением записи и `null`. Полудоверие здесь
 * опаснее отсутствия: подставленный мусор человек увидит как ошибку
 * приложения, а не как испорченный черновик.
 */
export function loadDraft(): DraftFields | null {
  let raw: string | null;
  try {
    raw = localStorage.getItem(STORAGE_KEY);
  } catch {
    // Приватный режим Safari: хранилище есть, запись и чтение бросают
    return null;
  }
  if (!raw) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    clearDraft();
    return null;
  }

  if (typeof parsed !== "object" || parsed === null) {
    clearDraft();
    return null;
  }
  const d = parsed as Record<string, unknown>;

  if (d.v !== VERSION) {
    clearDraft();
    return null;
  }
  if (typeof d.savedAt !== "number" || Date.now() - d.savedAt > TTL_MS) {
    clearDraft();
    return null;
  }

  const str = (key: string): string => (typeof d[key] === "string" ? (d[key] as string) : "");

  const draft: DraftFields = {
    index: Number.isInteger(d.index) && (d.index as number) >= 0 ? (d.index as number) : 0,
    name: str("name"),
    age: str("age"),
    gender: str("gender"),
    lookingFor: str("lookingFor"),
    city: str("city"),
    coords: isCoords(d.coords) ? d.coords : null,
    photos: isStringArray(d.photos) ? d.photos : [],
    interests: isStringArray(d.interests) ? d.interests : [],
    goal: str("goal"),
    relationType: str("relationType"),
    subculture: str("subculture"),
    mbti: str("mbti"),
    height: str("height"),
    bio: str("bio"),
  };

  // Пустой черновик равносилен отсутствию: он бы показал плашку
  // «восстановлено» там, где восстанавливать нечего.
  const пусто =
    draft.index === 0 &&
    !draft.name &&
    !draft.age &&
    !draft.gender &&
    !draft.lookingFor &&
    !draft.city &&
    draft.photos.length === 0 &&
    draft.interests.length === 0 &&
    !draft.goal &&
    !draft.relationType &&
    !draft.subculture &&
    !draft.mbti &&
    !draft.height &&
    !draft.bio;

  if (пусто) {
    clearDraft();
    return null;
  }

  return draft;
}

/**
 * Записать черновик. Ошибку хранилища глушим: переполненная квота или
 * приватный режим не должны ломать саму анкету — она работает и без
 * восстановления, просто хуже.
 */
export function saveDraft(fields: DraftFields): void {
  const payload: OnboardingDraft = { v: VERSION, savedAt: Date.now(), ...fields };
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  } catch {
    /* анкета важнее черновика */
  }
}

export function clearDraft(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* см. saveDraft */
  }
}
