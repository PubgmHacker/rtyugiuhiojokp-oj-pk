/**
 * Видеокружок в переписке — в той форме, что выбрал отправитель.
 *
 * Без пузыря: как и в мессенджерах, кружок сам себе пузырь, а подложка под
 * звездой или ёлкой сделала бы из фигуры «картинку в рамке». Обводка по
 * контуру формы — это и есть прогресс воспроизведения (stroke-dasharray по
 * реальной длине контура — один и тот же путь служит маской, обводкой и иконкой).
 *
 * Тап — играть со звуком / пауза. Играет один кружок за раз (playbackFocus).
 */

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Play } from "lucide-react";
import type { ChatMedia } from "../lib/api";
import { noteMaskStyle, noteShape } from "../lib/noteShapes";
import { claimPlayback } from "../lib/playbackFocus";
import { haptic } from "../lib/haptics";
import { formatClock } from "./VoiceBubble";

interface Props {
  media: ChatMedia;
  mine: boolean;
  /** Сторона кружка, px. */
  size?: number;
}

export default function VideoNoteBubble({ media, mine, size = 200 }: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const releaseRef = useRef<(() => void) | null>(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [failed, setFailed] = useState(false);
  // Длину контура меряем по факту: Chrome игнорирует pathLength при
  // non-scaling-stroke, и dasharray «100» рисовал бы половину звезды.
  const ringRef = useRef<SVGPathElement | null>(null);
  const [ringLength, setRingLength] = useState(300);
  // Первый кадр не грузим заранее — в истории таких сообщений может быть
  // много. Постер нарисуется после первого play через preload=metadata.
  const shape = noteShape(media.shape || undefined);
  const duration = Math.max(1, media.duration || 1);

  useLayoutEffect(() => {
    const ring = ringRef.current;
    if (!ring || typeof ring.getTotalLength !== "function") return;
    try {
      const len = ring.getTotalLength();
      if (len > 0) setRingLength(len);
    } catch {
      /* jsdom и старые движки без геометрии — остаётся оценка */
    }
  }, [shape.code]);

  useEffect(() => {
    const el = videoRef.current;
    if (!el) return;
    const onTime = () => setProgress(Math.min(1, el.currentTime / duration));
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
    const el = videoRef.current;
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

  return (
    <div className="flex flex-col gap-1" style={{ width: size }}>
      <button
        type="button"
        aria-label={playing ? "Пауза" : `Смотреть видеосообщение, ${shape.title.toLowerCase()}`}
        onClick={toggle}
        disabled={failed}
        className="relative block active:scale-[0.98] transition-transform disabled:opacity-50"
        style={{ width: size, height: size }}
      >
        <div
          className="absolute inset-0 bg-text/10 note-shape"
          style={noteMaskStyle(shape.code)}
        >
          <video
            ref={videoRef}
            src={media.url}
            poster={media.poster || undefined}
            preload="metadata"
            playsInline
            className="w-full h-full object-cover"
          />
        </div>

        {/* Контур формы: тонкая подложка и поверх неё прогресс */}
        <svg
          viewBox="0 0 100 100"
          aria-hidden="true"
          className="absolute inset-0 w-full h-full pointer-events-none"
        >
          <path
            d={shape.d}
            fill="none"
            stroke={mine ? "var(--color-accent)" : "currentColor"}
            strokeOpacity={0.28}
            strokeWidth={2.2}
            vectorEffect="non-scaling-stroke"
          />
          <path
            d={shape.d}
            fill="none"
            stroke="var(--color-accent)"
            strokeWidth={1.6}
            strokeLinecap="round"
            strokeLinejoin="round"
            ref={ringRef}
            strokeDasharray={ringLength}
            strokeDashoffset={ringLength * (1 - progress)}
            style={{ transition: "stroke-dashoffset 0.25s linear" }}
          />
        </svg>

        {!playing && !failed && (
          <span
            aria-hidden="true"
            className="absolute inset-0 flex items-center justify-center"
          >
            <span className="w-12 h-12 rounded-full liquid liquid-photo flex items-center justify-center">
              <Play size={20} fill="currentColor" strokeWidth={0} className="translate-x-[1px]" />
            </span>
          </span>
        )}
      </button>

      <div
        className={`flex items-center gap-1.5 text-[11.5px] tabular-nums px-1 ${
          mine ? "justify-end" : "justify-start"
        } text-text-muted`}
      >
        <span className="px-2 py-0.5 rounded-full bg-black/35 text-white/90">
          {failed ? "Не удалось воспроизвести" : formatClock(playing ? progress * duration : duration)}
        </span>
      </div>
    </div>
  );
}
