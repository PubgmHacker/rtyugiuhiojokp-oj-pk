/**
 * Кадры из видео для обложки ролика и для модерации.
 *
 * Сервер видео не разбирает — тащить ffmpeg в образ ради кадров дорого,
 * а без проверенных кадров в ленту попадёт что угодно. Поэтому кадры снимает
 * браузер: он всё равно уже декодирует видео для превью.
 *
 * Кадр берём не один: по одному кадру из начала нельзя поручиться за всё
 * видео — безобидное начало и нарушение дальше по ролику проходили модерацию.
 */

/** Со какой секунды берём кадр: на нулевой у многих видео чёрный экран. */
const FRAME_AT_SECONDS = 0.5;
/** Больше в ленте не нужно, а вес обложки бьёт по трафику. */
const MAX_COVER_SIDE = 720;
/**
 * Доли длительности, на которых снимаем кадры — строго по возрастанию:
 * сервер берёт обложкой ленты средний элемент списка, и порядок по времени
 * делает этим элементом середину ролика, а не случайный кадр.
 */
const FRAME_FRACTIONS = [0.1, 0.5, 0.9];

export class CoverFailed extends Error {}

/**
 * Снять кадры из видеофайла на разных таймкодах и вернуть их как JPEG.
 *
 * Кадры идут по возрастанию времени. Их модерирует сервер, и средний из них
 * становится обложкой в ленте.
 *
 * Бросает CoverFailed, если браузер не смог декодировать файл: это же значит,
 * что и в ленте видео не проиграется, и публиковать его незачем.
 */
export async function grabVideoCovers(file: File): Promise<Blob[]> {
  const url = URL.createObjectURL(file);
  const video = document.createElement("video");
  video.muted = true;
  video.playsInline = true;
  video.preload = "metadata";
  video.src = url;

  try {
    await new Promise<void>((resolve, reject) => {
      // Без таймаута сломанный файл оставил бы интерфейс в вечной загрузке
      const timer = window.setTimeout(
        () => reject(new CoverFailed("Не удалось прочитать видео")),
        15000
      );
      video.onloadeddata = () => {
        window.clearTimeout(timer);
        resolve();
      };
      video.onerror = () => {
        window.clearTimeout(timer);
        reject(new CoverFailed("Формат видео не поддерживается"));
      };
    });

    const scale = Math.min(
      1,
      MAX_COVER_SIDE / Math.max(video.videoWidth || 1, video.videoHeight || 1)
    );
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round((video.videoWidth || MAX_COVER_SIDE) * scale));
    canvas.height = Math.max(1, Math.round((video.videoHeight || MAX_COVER_SIDE) * scale));

    const ctx = canvas.getContext("2d");
    if (!ctx) throw new CoverFailed("Браузер не поддерживает обработку кадра");

    const duration = Number.isFinite(video.duration) ? video.duration : 0;
    const frames: Blob[] = [];

    for (const fraction of FRAME_FRACTIONS) {
      // У очень коротких (или нечитаемой длительности) роликов таймкоды
      // схлопываются в один и тот же кадр — это нормально: модерация всё равно
      // получит нужное число кадров, а видео там и есть один момент.
      const target = duration > 0 ? duration * fraction : FRAME_AT_SECONDS;
      await seekTo(video, target);
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob(resolve, "image/jpeg", 0.82)
      );
      if (!blob) throw new CoverFailed("Не удалось сохранить кадр");
      frames.push(blob);
    }

    return frames;
  } finally {
    // Освобождаем и объект, и сам элемент: иначе браузер держит файл в памяти
    video.src = "";
    URL.revokeObjectURL(url);
  }
}

/**
 * Перемотать к нужной секунде и дождаться отрисовки кадра.
 *
 * Ожидание отдельное: сразу после loadeddata и сразу после присвоения
 * currentTime кадр может быть ещё не готов. Если seek не сработает, идём
 * дальше с текущим кадром — пустой обложки это не даёт.
 */
function seekTo(video: HTMLVideoElement, seconds: number): Promise<void> {
  return new Promise<void>((resolve) => {
    if (!Number.isFinite(seconds) || seconds <= 0) {
      resolve();
      return;
    }
    const timer = window.setTimeout(resolve, 3000);
    video.onseeked = () => {
      window.clearTimeout(timer);
      resolve();
    };
    video.currentTime = seconds;
  });
}

/** Длительность видео в секундах; 0 — если прочитать не удалось. */
export async function videoDuration(file: File): Promise<number> {
  const url = URL.createObjectURL(file);
  const video = document.createElement("video");
  video.preload = "metadata";
  video.src = url;
  try {
    return await new Promise<number>((resolve) => {
      const done = (value: number) => resolve(value);
      video.onloadedmetadata = () => done(video.duration || 0);
      video.onerror = () => done(0);
      window.setTimeout(() => done(0), 10000);
    });
  } finally {
    video.src = "";
    URL.revokeObjectURL(url);
  }
}
