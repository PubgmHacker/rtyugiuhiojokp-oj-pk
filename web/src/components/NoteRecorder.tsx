/**
 * Панель записи голосового или видеокружка — встаёт на место поля ввода.
 *
 * Тап, а не удержание: в WebView Telegram долгое нажатие перехватывается
 * системным меню, и половина записей обрывалась бы на первой секунде. Поэтому
 * запись идёт до «Отправить» или до минуты, «Отмена» выбрасывает её.
 *
 * Для видео здесь же выбирают форму кружка — она едет с сообщением, и
 * получатель видит ту же звезду. Выбор запоминается на устройстве.
 */

import { useEffect, useRef, useState } from "react";
import { Send, Trash2 } from "lucide-react";
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

interface Props {
  kind: NoteKind;
  /** Запись готова: файл, длительность, волна/кадры и форма кружка. */
  onDone: (rec: Recording, shape: string, kind: NoteKind) => void;
  onCancel: () => void;
  /** Не удалось начать: нет доступа к микрофону/камере и т.п. */
  onError: (message: string) => void;
  /** Родитель грузит файл — кнопки заперты, чтобы не отправить дважды. */
  busy?: boolean;
}

const LIVE_BARS = 32;

export default function NoteRecorder({ kind, onDone, onCancel, onError, busy }: Props) {
  const handleRef = useRef<RecorderHandle | null>(null);
  const previewRef = useRef<HTMLVideoElement | null>(null);
  const finishedRef = useRef(false);
  const [seconds, setSeconds] = useState(0);
  const [ready, setReady] = useState(false);
  const [levels, setLevels] = useState<number[]>(() => Array(LIVE_BARS).fill(0));
  const [shape, setShape] = useState<string>(() => readPreferredShape());

  // Родительские колбэки — через реф: эффект записи стартует один раз,
  // а замыкания родителя меняются каждый рендер
  const cbs = useRef({ onDone, onCancel, onError });
  cbs.current = { onDone, onCancel, onError };
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

  const pickShape = (code: string) => {
    setShape(code);
    savePreferredShape(code);
    haptic("light");
  };

  const left = MAX_NOTE_SECONDS - seconds;

  return (
    <div role="group" aria-label={kind === "voice" ? "Запись голосового" : "Запись видеосообщения"}>
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

        <div className="flex-1 min-w-0 h-11 rounded-[22px] field flex items-center gap-2.5 px-3.5">
          <span className="rec-dot shrink-0" aria-hidden="true" />
          <span className="text-[14px] tabular-nums font-semibold shrink-0" aria-live="off">
            {formatClock(seconds)}
          </span>
          {kind === "voice" ? (
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

        <button
          type="button"
          aria-label="Отправить запись"
          onClick={() => void finish()}
          disabled={!ready || busy || seconds < 1}
          className="w-11 h-11 rounded-full liquid-primary shrink-0 rec-halo
                     flex items-center justify-center disabled:opacity-40
                     active:scale-95 transition-transform"
        >
          <Send size={18} />
        </button>
      </div>
    </div>
  );
}
