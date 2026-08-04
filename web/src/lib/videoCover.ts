/**
 * Кадр из видео для обложки ролика.
 *
 * Сервер видео не разбирает — тащить ffmpeg в образ ради одного кадра дорого,
 * а без проверенной обложки в ленту попадёт что угодно. Поэтому кадр снимает
 * браузер: он всё равно уже декодирует видео для превью.
 */

/** Со какой секунды берём кадр: на нулевой у многих видео чёрный экран. */
const FRAME_AT_SECONDS = 0.5;
/** Больше в ленте не нужно, а вес обложки бьёт по трафику. */
const MAX_COVER_SIDE = 720;

export class CoverFailed extends Error {}

/**
 * Снять кадр из видеофайла и вернуть его как JPEG.
 *
 * Бросает CoverFailed, если браузер не смог декодировать файл: это же значит,
 * что и в ленте видео не проиграется, и публиковать его незачем.
 */
export async function grabVideoCover(file: File): Promise<Blob> {
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

    // Перемотка нужна отдельным ожиданием: сразу после loadeddata кадр может
    // быть ещё не отрисован
    await new Promise<void>((resolve) => {
      const target = Math.min(FRAME_AT_SECONDS, (video.duration || 1) / 2);
      if (!Number.isFinite(target) || target <= 0) {
        resolve();
        return;
      }
      video.onseeked = () => resolve();
      video.currentTime = target;
      // Если seek не сработает, всё равно продолжаем с текущим кадром
      window.setTimeout(resolve, 3000);
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
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", 0.82)
    );
    if (!blob) throw new CoverFailed("Не удалось сохранить обложку");
    return blob;
  } finally {
    // Освобождаем и объект, и сам элемент: иначе браузер держит файл в памяти
    video.src = "";
    URL.revokeObjectURL(url);
  }
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
