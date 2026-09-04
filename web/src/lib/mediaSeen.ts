/**
 * «Не прослушано» — точка у голосового и у кружка, пока их не открыли со звуком.
 *
 * Сервер такого признака не хранит: он про своё устройство, а не про аккаунт.
 * Прослушал на телефоне — точка гаснет там, на вебе останется, и это честнее,
 * чем отметка «прочитано» от чужой сессии. Список ограничен и обрезается с
 * головы, иначе за год переписки localStorage распухнет на пустом месте.
 */

const STORAGE_KEY = "sd_media_played";
const MAX_ITEMS = 500;

let cache: string[] | null = null;

function загрузить(): string[] {
  if (cache) return cache;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    cache = Array.isArray(parsed) ? parsed.filter((v) => typeof v === "string") : [];
  } catch {
    cache = [];
  }
  return cache;
}

/** Ключ на сообщение: id уникален в пределах чата, kind разводит голос и кружок. */
export function mediaKey(kind: string, id: number | string): string {
  return `${kind}:${id}`;
}

export function wasPlayed(key: string): boolean {
  return загрузить().includes(key);
}

export function markPlayed(key: string): void {
  const список = загрузить();
  if (список.includes(key)) return;
  список.push(key);
  if (список.length > MAX_ITEMS) список.splice(0, список.length - MAX_ITEMS);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(список));
  } catch {
    /* приватный режим — точка просто вернётся после перезагрузки */
  }
}

/** Для тестов: сбросить и память процесса, и хранилище. */
export function resetPlayed(): void {
  cache = null;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* нечего сбрасывать */
  }
}
