/**
 * Панель записи голосового или видеокружка — встаёт на место поля ввода.
 *
 * Кнопки «Отправить» здесь нет намеренно: запись начинается удержанием той же
 * общей кнопки справа, что и в Telegram, и палец с неё не уходит — отправляет
 * и закрепляет её родитель через {@link NoteControls}. Пока держат (locked
 * false) панель показывает, куда вести палец; закрепили — появляется корзина,
 * а общая кнопка становится «Отправить».
 *
 * Про долгое нажатие в WebView: системное меню ловит его на тексте и картинках,
 * поэтому кнопка-курок — «немая» (без выделения и вызова меню), а перехваченный
 * жест (pointercancel) не теряет дубль — родитель закрепляет запись.
 *
 * Для видео здесь же выбирают форму кружка — она едет с сообщением, и
 * получатель видит ту же звезду. Выбор запоминается на устройстве.
 */

import { useEffect, useRef, useState } from "react";
import { Trash2 } from "lucide-react";
import {
  MAX_NOTE_SECONDS,
  describeRecorderError,
  startRecording,
  type NoteKind,
  type RecorderHandle,
  type Recording,
} from "../lib/recorder";
import {
  NOTE_SHAPES,
  noteMaskStyle,
  readPreferredShape,
  savePreferredShape,
} from "../lib/noteShapes";
import { haptic } from "../lib/haptics";
import { formatClock } from "./VoiceBubble";

/** Чем закончилось отпускание пальца. */
export type NoteStopResult =
  /** Ушла в отправку. */
  | "sent"
  /** Меньше секунды — выбросили, записывать нечего. */
  | "short"
  /** Микрофон/камера ещё поднимались: запись живёт, её надо закрепить. */
  | "cold";

export interface NoteControls {
  stop: () => NoteStopResult;
  cancel: () => void;
}

/** Меньше этого держать бессмысленно — в Telegram такой дубль тоже улетает. */
const MIN_NOTE_MS = 900;

interface Props {
  kind: NoteKind;
  /** Палец отпустили, запись продолжается сама: корзина и «Отправить» живут. */
  locked?: boolean;
  /** Отдаёт родителю «отправить»/«отменить»: курок — его кнопка. */
  onControls?: (controls: NoteControls | null) => void;
  /** Микрофон/камера поднялись — родитель разблокирует «Отправить». */
  onReady?: () => void;
  /** Запись готова: файл, длительность, волна/кадры и форма кружка. */
  onDone: (rec: Recording, shape: string, kind: NoteKind) => void;
  onCancel: () => void;
  /** Не удалось начать: нет доступа к микрофону/камере и т.п. */
  onError: (message: string) => void;
  /** Родитель грузит файл — кнопки заперты, чтобы не отправить дважды. */
  busy?: boolean;
}

const LIVE_BARS = 32;

export default function NoteRecorder({
  kind,
  locked = true,
  onControls,
  onReady,
  onDone,
  onCancel,
  onError,
  busy,
}: Props) {
  const handleRef = useRef<RecorderHandle | null>(null);
  const previewRef = useRef<HTMLVideoElement | null>(null);
  const finishedRef = useRef(false);
  const startedAtRef = useRef(0);
  const [seconds, setSeconds] = useState(0);
  const [ready, setReady] = useState(false);
  const [levels, setLevels] = useState<number[]>(() => Array(LIVE_BARS).fill(0));
  const [shape, setShape] = useState<string>(() => readPreferredShape());

  // Родительские колбэки — через реф: эффект записи стартует один раз,
  // а замыкания родителя меняются каждый рендер
  const cbs = useRef({ onDone, onCancel, onError, onControls, onReady });
  cbs.current = { onDone, onCancel, onError, onControls, onReady };
  const shapeRef = useRef(shape);
  shapeRef.current = shape;

  useEffect(() => {
    let alive = true;
    let offLevel: (() => void) | null = null;
    let timer: ReturnType<typeof setInterval> | null = null;

    (async () => {
      try {
        const h = await startRecording(kind);
        if (!alive) {
          h.cancel();
          return;
        }
        handleRef.current = h;
        startedAtRef.current = Date.now();
        if (kind === "video_note" && previewRef.current) h.attachPreview(previewRef.current);
        offLevel = h.onLevel((l) =>
          setLevels((cur) => [...cur.slice(1), l])
        );
        const startedAt = Date.now();
        timer = setInterval(() => {
          const s = Math.floor((Date.now() - startedAt) / 1000);
          setSeconds(s);
          if (s >= MAX_NOTE_SECONDS) void finish();
        }, 250);
        setReady(true);
        cbs.current.onReady?.();
        haptic("medium");
      } catch (e) {
        if (!alive) return;
        cbs.current.onError(describeRecorderError(e, kind));
      }
    })();

    return () => {
      alive = false;
      offLevel?.();
      if (timer) clearInterval(timer);
      // Ушли с экрана посреди записи — микрофон и камеру отпускаем
      if (!finishedRef.current) handleRef.current?.cancel();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind]);

  const finish = async () => {
    const h = handleRef.current;
    if (!h || finishedRef.current) return;
    finishedRef.current = true;
    haptic("light");
    try {
      const rec = await h.stop();
      cbs.current.onDone(rec, shapeRef.current, kind);
    } catch {
      cbs.current.onError("Запись не сохранилась — попробуйте ещё раз");
    }
  };

  const cancel = () => {
    if (finishedRef.current) return;
    finishedRef.current = true;
    handleRef.current?.cancel();
    haptic("light");
    cbs.current.onCancel();
  };

  // Палец отпустили над общей кнопкой. Родитель не знает ни про хэндл, ни про
  // секунды — решаем здесь и отвечаем, что стало с дублем.
  const stop = (): NoteStopResult => {
    if (finishedRef.current) return "sent";
    if (!handleRef.current || !startedAtRef.current) return "cold";
    if (Date.now() - startedAtRef.current < MIN_NOTE_MS) {
      cancel();
      return "short";
    }
    void finish();
    return "sent";
  };

  // Курок отдаём один раз на монтирование: замыкания читают рефы, устареть
  // им нечем, а пересоздание пары каждый рендер сбивало бы жест родителя.
  useEffect(() => {
    cbs.current.onControls?.({ stop, cancel });
    return () => cbs.current.onControls?.(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pickShape = (code: string) => {
    setShape(code);
    savePreferredShape(code);
    haptic("light");
  };

  const left = MAX_NOTE_SECONDS - seconds;

  return (
    <div
      className="flex-1 min-w-0"
      role="group"
      aria-label={kind === "voice" ? "Запись голосового" : "Запись видеосообщения"}
    >
      {kind === "video_note" && (
        <div className="flex flex-col items-center gap-3 pb-3">
          <div className="relative w-[168px] h-[168px]">
            <div
              className="absolute inset-0 bg-black/50 note-shape"
              style={noteMaskStyle(shape)}
            >
              <video
                ref={previewRef}
                muted
                playsInline
                autoPlay
                className="w-full h-full object-cover"
                style={{ transform: "scaleX(-1)" }}
              />
            </div>
            {!ready && (
              <span className="absolute inset-0 flex items-center justify-center text-[12px] text-white/80">
                Включаем камеру…
              </span>
            )}
          </div>

          <div
            hidden={!locked}
            role="radiogroup"
            aria-label="Форма кружка"
            className="flex gap-1.5 overflow-x-auto no-scrollbar max-w-full px-1"
          >
            {NOTE_SHAPES.map((s) => {
              const active = s.code === shape;
              return (
                <button
                  key={s.code}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  aria-label={s.title}
                  onClick={() => pickShape(s.code)}
                  className={`w-10 h-10 rounded-full shrink-0 flex items-center justify-center
                              transition-transform active:scale-90 ${
                                active ? "liquid-primary" : "chip text-text-muted"
                              }`}
                >
                  <svg viewBox="0 0 100 100" width={20} height={20} aria-hidden="true">
                    <path d={s.d} fill="currentColor" />
                  </svg>
                </button>
              );
            })}
          </div>
        </div>
      )}

      <div className="flex items-center gap-2">
        {locked && (
          <button
            type="button"
            aria-label="Отменить запись"
            onClick={cancel}
            disabled={busy}
            className="w-11 h-11 rounded-full chip text-danger shrink-0
                       flex items-center justify-center active:scale-95 transition-transform
                       disabled:opacity-40"
          >
            <Trash2 size={18} />
          </button>
        )}

        <div className="flex-1 min-w-0 h-11 rounded-[22px] field flex items-center gap-2.5 px-3.5">
          <span className="rec-dot shrink-0" aria-hidden="true" />
          <span className="text-[14px] tabular-nums font-semibold shrink-0" aria-live="off">
            {formatClock(seconds)}
          </span>
          {!locked ? (
            <span className="flex-1 min-w-0 text-right text-[12.5px] text-text-muted truncate">
              ← отмена · ↑ закрепить
            </span>
          ) : kind === "voice" ? (
            <div className="flex-1 flex items-center gap-[2px] h-6" aria-hidden="true">
              {levels.map((l, i) => (
                <span
                  key={i}
                  className="flex-1 min-w-[2px] rounded-full bg-accent"
                  style={{
                    height: `${18 + l * 82}%`,
                    opacity: 0.45 + l * 0.55,
                    transition: "height 90ms linear",
                  }}
                />
              ))}
            </div>
          ) : (
            <span className="flex-1 text-[12.5px] text-text-muted truncate">
              {ready ? "Идёт запись" : "Готовим камеру…"}
            </span>
          )}
          {left <= 10 && (
            <span className="text-[11.5px] text-warn tabular-nums shrink-0">−{left}</span>
          )}
        </div>
      </div>
    </div>
  );
}
