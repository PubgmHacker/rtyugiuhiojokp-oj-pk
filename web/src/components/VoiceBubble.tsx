/**
 * Голосовое сообщение в переписке.
 *
 * Волна рисуется по цифрам `media.waveform` (0–9 на столбик), записанным
 * отправителем по ходу записи: аудио на приёмнике не декодируется, а webm без
 * длительности в заголовке ещё и врёт про `duration`. Поэтому и время берём
 * из сообщения, а не из элемента, и прогресс считаем сами по `timeupdate`.
 *
 * Как в Telegram: по волне не тапают, а ведут пальцем — позиция идёт следом,
 * и это единственный способ попасть в нужное слово. Скорость 1× / 1,5× / 2×
 * появляется, когда есть что ускорять; точка у времени горит, пока запись не
 * слушали. Играет одна дорожка за раз (playbackFocus): две голосовые
 * одновременно — это шум, а не переписка.
 */

import { useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { Pause, Play } from "lucide-react";
import type { ChatMedia } from "../lib/api";
import { claimPlayback } from "../lib/playbackFocus";
import { markPlayed, mediaKey, wasPlayed } from "../lib/mediaSeen";
import { haptic } from "../lib/haptics";

interface Props {
  media: ChatMedia;
  /** Своё сообщение — краски на акцентном фоне; чужое — на карточке. */
  mine: boolean;
}

/** Ровная волна на случай записи без анализатора громкости. */
const FLAT_WAVEFORM = "3454645354634536454635463545";
/** Столбиков в пузыре всегда одно число — волна не растягивает пузырь. */
const BAR_COUNT = 40;
/** Порядок скоростей по кругу — как в мессенджерах, без выпадающего меню. */
const SPEEDS = [1, 1.5, 2] as const;

function resampleBars(src: string, count = BAR_COUNT): string {
  if (src.length === count) return src;
  let out = "";
  for (let i = 0; i < count; i += 1) {
    const from = Math.floor((i / count) * src.length);
    const to = Math.max(from + 1, Math.floor(((i + 1) / count) * src.length));
    let peak = 0;
    for (let j = from; j < to; j += 1) peak = Math.max(peak, Number(src[j]) || 0);
    out += String(Math.min(9, peak));
  }
  return out;
}

export function formatClock(seconds: number): string {
  // Не число — ноль, а не «NaN:NaN». Длительность приходит из четырёх мест
  // (медиа сообщения, цитата, запись, черновик), и хватает одного, где её
  // ещё нет, чтобы человек увидел в переписке отладочный мусор
  const s = Number.isFinite(seconds) ? Math.max(0, Math.round(seconds)) : 0;
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function подписьСкорости(v: number): string {
  return `${String(v).replace(".", ",")}×`;
}

export default function VoiceBubble({ media, mine }: Props) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const waveRef = useRef<HTMLDivElement | null>(null);
  const releaseRef = useRef<(() => void) | null>(null);
  const scrubRef = useRef(false);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0); // 0..1
  const [failed, setFailed] = useState(false);
  const [speedIdx, setSpeedIdx] = useState(0);
  const ключ = mediaKey("voice", media.url);
  const [unheard, setUnheard] = useState(() => !wasPlayed(ключ));

  const bars = resampleBars(media.waveform && media.waveform.length >= 8 ? media.waveform : FLAT_WAVEFORM)
    .split("")
    .map((ch) => Number(ch) || 0);
  const duration = Math.max(1, media.duration || 1);
  const speed = SPEEDS[speedIdx];

  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    const onTime = () => {
      // Длительность элемента у webm ненадёжна — делим на своё время
      if (!scrubRef.current) setProgress(Math.min(1, el.currentTime / duration));
    };
    const onEnd = () => {
      setPlaying(false);
      setProgress(0);
      releaseRef.current?.();
      releaseRef.current = null;
    };
    const onPause = () => setPlaying(false);
    const onPlay = () => setPlaying(true);
    const onError = () => {
      setFailed(true);
      setPlaying(false);
    };
    el.addEventListener("timeupdate", onTime);
    el.addEventListener("ended", onEnd);
    el.addEventListener("pause", onPause);
    el.addEventListener("play", onPlay);
    el.addEventListener("error", onError);
    return () => {
      el.removeEventListener("timeupdate", onTime);
      el.removeEventListener("ended", onEnd);
      el.removeEventListener("pause", onPause);
      el.removeEventListener("play", onPlay);
      el.removeEventListener("error", onError);
      releaseRef.current?.();
      releaseRef.current = null;
    };
  }, [duration]);

  // Скорость держим на элементе: смена по ходу воспроизведения не должна
  // прерывать звук
  useEffect(() => {
    const el = audioRef.current;
    if (el) el.playbackRate = speed;
  }, [speed]);

  const toggle = () => {
    const el = audioRef.current;
    if (!el || failed) return;
    haptic("light");
    if (el.paused) {
      releaseRef.current?.();
      releaseRef.current = claimPlayback(() => el.pause());
      el.playbackRate = speed;
      el.play().catch(() => setFailed(true));
      if (unheard) {
        markPlayed(ключ);
        setUnheard(false);
      }
    } else {
      el.pause();
    }
  };

  const применить = (доля: number) => {
    const el = audioRef.current;
    const d = Math.max(0, Math.min(1, доля));
    setProgress(d);
    if (!el || failed) return;
    try {
      el.currentTime = d * duration;
    } catch {
      /* поток ещё не готов к перемотке — не страшно */
    }
  };

  const доляПоX = (clientX: number): number => {
    const r = waveRef.current?.getBoundingClientRect();
    if (!r || r.width === 0) return 0;
    return (clientX - r.left) / r.width;
  };

  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (failed || e.button !== 0) return;
    scrubRef.current = true;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    применить(доляПоX(e.clientX));
  };

  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!scrubRef.current) return;
    применить(доляПоX(e.clientX));
  };

  const onPointerUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!scrubRef.current) return;
    scrubRef.current = false;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    haptic("light");
  };

  const шагом = (сек: number) => применить(progress + сек / duration);

  const ink = mine ? "text-white" : "text-text";
  const shown = playing || progress > 0 ? progress * duration : duration;
  const активна = playing || progress > 0;

  return (
    <div className="flex items-center gap-2.5 py-0.5 w-[238px] max-w-full">
      <audio ref={audioRef} src={media.url} preload="none" />
      <button
        type="button"
        aria-label={playing ? "Пауза" : "Слушать голосовое"}
        onClick={toggle}
        disabled={failed}
        className={`w-10 h-10 rounded-full shrink-0 flex items-center justify-center
                    active:scale-90 transition-transform disabled:opacity-40 ${
                      mine ? "bg-white/22 text-white" : "liquid-primary"
                    }`}
      >
        {playing ? (
          <Pause size={17} fill="currentColor" strokeWidth={0} />
        ) : (
          <Play size={17} fill="currentColor" strokeWidth={0} className="translate-x-[1px]" />
        )}
      </button>

      <div className="flex-1 min-w-0">
        <div
          ref={waveRef}
          role="slider"
          aria-label="Позиция воспроизведения"
          aria-valuemin={0}
          aria-valuemax={duration}
          aria-valuenow={Math.round(progress * duration)}
          aria-valuetext={formatClock(progress * duration)}
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "ArrowRight") {
              e.preventDefault();
              шагом(3);
            }
            if (e.key === "ArrowLeft") {
              e.preventDefault();
              шагом(-3);
            }
          }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          data-scrub="bar"
          className="relative flex items-center gap-[2px] h-7 cursor-pointer touch-none"
        >
          {bars.map((v, i) => {
            const done = (i + 0.5) / bars.length <= progress;
            return (
              <span
                key={i}
                aria-hidden="true"
                className={`flex-1 min-w-0 rounded-full transition-opacity duration-150 ${ink}`}
                style={{
                  height: `${22 + v * 8}%`,
                  backgroundColor: "currentColor",
                  opacity: done ? 1 : mine ? 0.42 : 0.3,
                }}
              />
            );
          })}
        </div>

        <div
          className={`flex items-center gap-1.5 text-[11.5px] tabular-nums ${
            mine ? "text-white/80" : "text-text-muted"
          }`}
        >
          <span>{failed ? "Не удалось воспроизвести" : formatClock(shown)}</span>
          {unheard && !failed && (
            <span
              className={`w-[5px] h-[5px] rounded-full ${mine ? "bg-white" : "bg-accent"}`}
              aria-label="не прослушано"
            />
          )}
        </div>
      </div>

      {/* Скорость — только когда есть что ускорять */}
      {активна && !failed && (
        <button
          type="button"
          aria-label={`Скорость воспроизведения ${подписьСкорости(speed)}`}
          onClick={(e) => {
            e.stopPropagation();
            haptic("light");
            setSpeedIdx((i) => (i + 1) % SPEEDS.length);
          }}
          className={`shrink-0 self-start mt-0.5 px-1.5 h-[22px] rounded-full
                      text-[10.5px] font-semibold tabular-nums leading-none
                      flex items-center justify-center active:scale-90
                      transition-transform ${
                        mine
                          ? "bg-white/22 text-white"
                          : "bg-text/10 text-text-muted"
                      }`}
        >
          {подписьСкорости(speed)}
        </button>
      )}
    </div>
  );
}
