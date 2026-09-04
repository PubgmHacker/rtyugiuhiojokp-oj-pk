/**
 * Голосовое сообщение в переписке.
 *
 * Волна рисуется по цифрам `media.waveform` (0–9 на столбик), записанным
 * отправителем по ходу записи: аудио на приёмнике не декодируется, а webm без
 * длительности в заголовке ещё и врёт про `duration`. Поэтому и время берём
 * из сообщения, а не из элемента, и прогресс считаем сами по `timeupdate`.
 *
 * Тап по волне — перемотка: столбик под пальцем становится текущим. Играет
 * одна запись за раз (playbackFocus): две голосовые дорожки одновременно —
 * это шум, а не переписка.
 */

import { useEffect, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";
import type { ChatMedia } from "../lib/api";
import { claimPlayback } from "../lib/playbackFocus";
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
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export default function VoiceBubble({ media, mine }: Props) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const releaseRef = useRef<(() => void) | null>(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0); // 0..1
  const [failed, setFailed] = useState(false);

  const bars = resampleBars(media.waveform && media.waveform.length >= 8 ? media.waveform : FLAT_WAVEFORM)
    .split("")
    .map((ch) => Number(ch) || 0);
  const duration = Math.max(1, media.duration || 1);

  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    const onTime = () => {
      // Длительность элемента у webm ненадёжна — делим на своё время
      setProgress(Math.min(1, el.currentTime / duration));
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

  const toggle = () => {
    const el = audioRef.current;
    if (!el || failed) return;
    haptic("light");
    if (el.paused) {
      releaseRef.current?.();
      releaseRef.current = claimPlayback(() => el.pause());
      el.play().catch(() => setFailed(true));
    } else {
      el.pause();
    }
  };

  const seek = (index: number) => {
    const el = audioRef.current;
    if (!el || failed) return;
    const t = (index / bars.length) * duration;
    try {
      el.currentTime = t;
      setProgress(t / duration);
    } catch {
      /* поток ещё не готов к перемотке — не страшно */
    }
  };

  const ink = mine ? "text-white" : "text-text";
  const shown = playing || progress > 0 ? progress * duration : duration;

  return (
    <div className="flex items-center gap-2.5 py-0.5 w-[226px] max-w-full">
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
          role="slider"
          aria-label="Позиция воспроизведения"
          aria-valuemin={0}
          aria-valuemax={duration}
          aria-valuenow={Math.round(progress * duration)}
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "ArrowRight") seek(Math.min(bars.length - 1, Math.floor(progress * bars.length) + 2));
            if (e.key === "ArrowLeft") seek(Math.max(0, Math.floor(progress * bars.length) - 2));
          }}
          className="flex items-center gap-[2px] h-7 cursor-pointer"
        >
          {bars.map((v, i) => {
            const done = i / bars.length < progress;
            return (
              <button
                key={i}
                type="button"
                tabIndex={-1}
                aria-hidden="true"
                onClick={() => seek(i)}
                className="flex-1 min-w-0 h-full flex items-center"
              >
                <span
                  className={`block w-full rounded-full transition-[opacity,background-color] duration-150 ${ink}`}
                  style={{
                    height: `${22 + v * 8}%`,
                    backgroundColor: "currentColor",
                    opacity: done ? 1 : mine ? 0.42 : 0.3,
                  }}
                />
              </button>
            );
          })}
        </div>
        <div className={`flex items-center gap-1.5 text-[11.5px] tabular-nums ${mine ? "text-white/80" : "text-text-muted"}`}>
          <span>{failed ? "Не удалось воспроизвести" : formatClock(shown)}</span>
        </div>
      </div>
    </div>
  );
}
