/**
 * Запись голосового и видеокружка в браузере.
 *
 * MediaRecorder отдаёт файл целиком, но нам нужно больше: волна голоса
 * (столбики в пузыре рисуются по ней, аудио на приёмнике не декодируется) и
 * кадры видео для модерации (сервер видео не разбирает — ffmpeg в контейнере
 * нет, тот же контракт, что у роликов). И то, и другое снимается ПО ХОДУ
 * записи: webm из MediaRecorder без длительности в заголовке, перемотка по
 * нему после записи ненадёжна, а анализатор громкости работает только на
 * живом потоке.
 *
 * Тип файла отдаём без параметров кодека: сервер сверяет `audio/webm`, а не
 * `audio/webm;codecs=opus`.
 */

export type NoteKind = "voice" | "video_note";

export interface Recording {
  blob: Blob;
  /** Секунды, 1..60. */
  duration: number;
  /** Цифры 0–9 — высоты столбиков; пусто у видео. */
  waveform: string;
  /** JPEG-кадры с разных моментов записи (только видео), ≥ 3. */
  covers: Blob[];
}

export interface RecorderHandle {
  kind: NoteKind;
  /** Громкость 0..1 каждые ~100 мс — для живого индикатора. */
  onLevel(cb: (level: number) => void): () => void;
  /** Показать камеру в элементе и снимать с него кадры для модерации. */
  attachPreview(video: HTMLVideoElement): void;
  stop(): Promise<Recording>;
  cancel(): void;
}

export class RecorderUnavailable extends Error {}

export const MAX_NOTE_SECONDS = 60;
/** Столбиков волны в сообщении — ширина пузыря больше не покажет. */
const WAVEFORM_BARS = 48;
const LEVEL_INTERVAL_MS = 100;
const FRAME_INTERVAL_MS = 700;
const FRAME_SIDE = 360;
const MIN_COVERS = 3;

const AUDIO_MIMES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
  "audio/ogg;codecs=opus",
];
const VIDEO_MIMES = [
  "video/webm;codecs=vp9,opus",
  "video/webm;codecs=vp8,opus",
  "video/webm",
  "video/mp4",
];

const KIND_KEY = "sd_note_kind";

/**
 * Чем записывали в прошлый раз. Кнопка в чате одна и общая: она поднимается
 * в том режиме, в котором её оставили, — как микрофон/камера в Telegram.
 */
export function readPreferredKind(): NoteKind {
  try {
    return localStorage.getItem(KIND_KEY) === "video_note" ? "video_note" : "voice";
  } catch {
    return "voice";
  }
}

export function savePreferredKind(kind: NoteKind): void {
  try {
    localStorage.setItem(KIND_KEY, kind);
  } catch {
    /* приватный режим — просто не запомним */
  }
}

export function recordingSupported(): boolean {
  return (
    typeof MediaRecorder !== "undefined" &&
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia
  );
}

function pickMime(kind: NoteKind): string {
  const list = kind === "voice" ? AUDIO_MIMES : VIDEO_MIMES;
  const supported = list.find((m) => {
    try {
      return MediaRecorder.isTypeSupported(m);
    } catch {
      return false;
    }
  });
  // Пустая строка — «на усмотрение браузера»: Safari так и хочет
  return supported ?? "";
}

/** Человеческое объяснение отказа getUserMedia / MediaRecorder. */
export function describeRecorderError(e: unknown, kind: NoteKind): string {
  const что = kind === "voice" ? "микрофону" : "камере и микрофону";
  const name = (e as { name?: string } | null)?.name;
  if (e instanceof RecorderUnavailable) {
    return "Браузер не умеет записывать — откройте приложение в Telegram посвежее";
  }
  if (name === "NotAllowedError" || name === "SecurityError") {
    return `Нет доступа к ${что}. Разрешите в настройках и попробуйте снова`;
  }
  if (name === "NotFoundError" || name === "OverconstrainedError") {
    return kind === "voice" ? "Микрофон не найден" : "Камера не найдена";
  }
  if (name === "NotReadableError") {
    return "Устройство занято другим приложением";
  }
  return "Не удалось начать запись";
}

export async function startRecording(kind: NoteKind): Promise<RecorderHandle> {
  if (!recordingSupported()) throw new RecorderUnavailable("MediaRecorder");

  const stream = await navigator.mediaDevices.getUserMedia(
    kind === "voice"
      ? { audio: { echoCancellation: true, noiseSuppression: true } }
      : {
          audio: { echoCancellation: true, noiseSuppression: true },
          video: {
            facingMode: "user",
            width: { ideal: 480 },
            height: { ideal: 480 },
            aspectRatio: { ideal: 1 },
          },
        }
  );

  const mime = pickMime(kind);
  let recorder: MediaRecorder;
  try {
    recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
  } catch (e) {
    stream.getTracks().forEach((t) => t.stop());
    throw new RecorderUnavailable(String(e));
  }

  const chunks: Blob[] = [];
  recorder.ondataavailable = (ev) => {
    if (ev.data && ev.data.size) chunks.push(ev.data);
  };

  // ── громкость: анализатор на живом потоке ──
  const levels: number[] = [];
  const levelListeners = new Set<(l: number) => void>();
  let audioCtx: AudioContext | null = null;
  let levelTimer: ReturnType<typeof setInterval> | null = null;
  try {
    const Ctx = window.AudioContext || (window as any).webkitAudioContext;
    if (Ctx && stream.getAudioTracks().length) {
      audioCtx = new Ctx();
      const src = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      src.connect(analyser);
      const buf = new Uint8Array(analyser.fftSize);
      levelTimer = setInterval(() => {
        analyser.getByteTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) {
          const v = (buf[i] - 128) / 128;
          sum += v * v;
        }
        // RMS тихой речи ~0.05, громкой ~0.3: растягиваем в 0..1
        const level = Math.min(1, Math.sqrt(sum / buf.length) * 3.2);
        levels.push(level);
        levelListeners.forEach((cb) => cb(level));
      }, LEVEL_INTERVAL_MS);
    }
  } catch {
    /* без анализатора волна будет ровной — не повод не записывать */
  }

  // ── кадры для модерации (видео) ──
  const frames: Blob[] = [];
  let previewEl: HTMLVideoElement | null = null;
  let frameTimer: ReturnType<typeof setInterval> | null = null;
  const canvas = document.createElement("canvas");
  canvas.width = FRAME_SIDE;
  canvas.height = FRAME_SIDE;
  const ctx = canvas.getContext("2d");

  const grabFrame = (): Promise<Blob | null> =>
    new Promise((resolve) => {
      const v = previewEl;
      if (!v || !ctx || v.videoWidth === 0 || v.videoHeight === 0) return resolve(null);
      // Квадрат по центру кадра — то, что и увидит получатель в кружке
      const side = Math.min(v.videoWidth, v.videoHeight);
      const sx = (v.videoWidth - side) / 2;
      const sy = (v.videoHeight - side) / 2;
      ctx.drawImage(v, sx, sy, side, side, 0, 0, FRAME_SIDE, FRAME_SIDE);
      canvas.toBlob((b) => resolve(b), "image/jpeg", 0.8);
    });

  const startedAt = Date.now();
  recorder.start(250);

  let finished = false;
  const cleanup = () => {
    if (levelTimer) clearInterval(levelTimer);
    if (frameTimer) clearInterval(frameTimer);
    levelTimer = frameTimer = null;
    stream.getTracks().forEach((t) => t.stop());
    if (previewEl) previewEl.srcObject = null;
    audioCtx?.close().catch(() => {});
  };

  return {
    kind,
    onLevel(cb) {
      levelListeners.add(cb);
      return () => levelListeners.delete(cb);
    },
    attachPreview(video) {
      if (kind !== "video_note") return;
      previewEl = video;
      video.srcObject = stream;
      video.muted = true;
      video.playsInline = true;
      video.play().catch(() => {});
      if (frameTimer) clearInterval(frameTimer);
      frameTimer = setInterval(() => {
        grabFrame().then((b) => {
          if (b) frames.push(b);
        });
      }, FRAME_INTERVAL_MS);
    },
    async stop() {
      if (finished) throw new Error("already stopped");
      finished = true;
      const stopped = new Promise<void>((resolve) => {
        recorder.onstop = () => resolve();
        // Safari иногда не шлёт onstop у мгновенно остановленной записи
        setTimeout(resolve, 2500);
      });
      if (recorder.state !== "inactive") recorder.stop();
      await stopped;

      // Кадры: минимум три с разных моментов; коротенькая запись добирает
      // текущим кадром — для секундного видео это и есть все его моменты
      let covers: Blob[] = [];
      if (kind === "video_note") {
        while (frames.length < MIN_COVERS) {
          const b = await grabFrame();
          if (!b) break;
          frames.push(b);
        }
        if (frames.length >= MIN_COVERS) {
          const mid = Math.floor(frames.length / 2);
          covers = [frames[0], frames[mid], frames[frames.length - 1]];
        } else {
          covers = frames.slice();
        }
      }
      cleanup();

      const baseType = (recorder.mimeType || mime || (kind === "voice" ? "audio/webm" : "video/webm"))
        .split(";")[0];
      const blob = new Blob(chunks, { type: baseType });
      const seconds = Math.max(
        1,
        Math.min(MAX_NOTE_SECONDS, Math.round((Date.now() - startedAt) / 1000))
      );
      return { blob, duration: seconds, waveform: kind === "voice" ? toWaveform(levels) : "", covers };
    },
    cancel() {
      if (finished) return;
      finished = true;
      try {
        if (recorder.state !== "inactive") recorder.stop();
      } catch {
        /* уже остановлен */
      }
      cleanup();
    },
  };
}

/**
 * Сжать ряд уровней громкости до WAVEFORM_BARS цифр 0–9.
 * Нормируем по максимуму записи: тихий голос всё равно даёт рельеф, а не
 * ровную полоску. Совсем тихие участки — 0.
 */
export function toWaveform(levels: number[]): string {
  if (!levels.length) return "";
  const bars = Math.min(WAVEFORM_BARS, Math.max(8, levels.length));
  const per = levels.length / bars;
  const buckets: number[] = [];
  for (let i = 0; i < bars; i++) {
    const from = Math.floor(i * per);
    const to = Math.max(from + 1, Math.floor((i + 1) * per));
    let peak = 0;
    for (let j = from; j < to && j < levels.length; j++) peak = Math.max(peak, levels[j]);
    buckets.push(peak);
  }
  const max = Math.max(...buckets, 0.05);
  return buckets
    .map((b) => {
      const n = Math.round((b / max) * 9);
      return String(Math.max(0, Math.min(9, n)));
    })
    .join("");
}
