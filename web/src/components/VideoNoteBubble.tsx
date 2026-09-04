/**
 * Видеокружок в переписке — в той форме, что выбрал отправитель.
 *
 * Как это работает у Telegram и ВКонтакте, и почему так же здесь:
 *  · кружок оживает сам, когда доезжает до экрана — без звука и по кругу.
 *    Серая кнопка «play» посреди лица — признак встроенного плеера, а не
 *    сообщения: в переписке первым делом смотрят на человека, а не на элемент
 *    управления. Поэтому центр чист;
 *  · в покое кружок компактный. Тап разворачивает его и включает звук с
 *    начала, повторный — сворачивает обратно в немой цикл. Один звук на весь
 *    экран (playbackFocus), поэтому развёрнут всегда ровно один кружок;
 *  · время и динамик живут ВНУТРИ фигуры, у её нижнего края (anchor у каждой
 *    формы свой — у звезды и ёлки низ это остриё). Плашка под кружком делала
 *    из сообщения «видео с подписью»;
 *  · обводка по контуру — прогресс. По ней же можно вести пальцем и
 *    перематывать: точка контура ищется по реальной геометрии пути, поэтому
 *    перемотка работает и на звезде, и на ёлке.
 *
 * Немой цикл выключается при prefers-reduced-motion — там остаётся постер и
 * тап. Точка «не смотрел» гаснет после первого просмотра со звуком.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import type { ChatMedia } from "../lib/api";
import { noteMaskStyle, noteShape } from "../lib/noteShapes";
import { claimPlayback } from "../lib/playbackFocus";
import { markPlayed, mediaKey, wasPlayed } from "../lib/mediaSeen";
import { haptic } from "../lib/haptics";
import { formatClock } from "./VoiceBubble";

interface Props {
  media: ChatMedia;
  mine: boolean;
  /** Сторона кружка в покое, px. Со звуком он вырастает сам. */
  size?: number;
}

/** Сторона развёрнутого кружка: узкие экраны режут по ширине колонки. */
const РАЗВЁРНУТЫЙ = "min(70vw, 244px)";

/** Точек контура для перемотки: 1.5° шага хватает даже на лучах звезды. */
const SAMPLES = 240;

interface Точка {
  x: number;
  y: number;
  t: number;
}

function бережноеДвижение(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

export default function VideoNoteBubble({ media, mine, size = 148 }: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const releaseRef = useRef<(() => void) | null>(null);
  const [sound, setSound] = useState(false);
  const [progress, setProgress] = useState(0);
  const [failed, setFailed] = useState(false);
  const [inView, setInView] = useState(false);
  const ключ = mediaKey("video_note", media.url);
  const [unseen, setUnseen] = useState(() => !wasPlayed(ключ));
  const [бережно] = useState(бережноеДвижение);

  // Длину контура меряем по факту: Chrome игнорирует pathLength при
  // non-scaling-stroke, и dasharray «100» рисовал бы половину звезды.
  const ringRef = useRef<SVGPathElement | null>(null);
  const [ringLength, setRingLength] = useState(300);
  const samplesRef = useRef<Точка[]>([]);
  const scrubRef = useRef(false);
  const [scrubbing, setScrubbing] = useState(false);

  const shape = noteShape(media.shape || undefined);
  const duration = Math.max(1, media.duration || 1);
  const inViewRef = useRef(false);
  inViewRef.current = inView;

  /* ── Геометрия контура: длина и таблица точек для перемотки ── */
  useLayoutEffect(() => {
    const ring = ringRef.current;
    if (!ring || typeof ring.getTotalLength !== "function") return;
    try {
      const len = ring.getTotalLength();
      if (!(len > 0)) return;
      setRingLength(len);
      const точки: Точка[] = [];
      for (let i = 0; i <= SAMPLES; i++) {
        const t = i / SAMPLES;
        const p = ring.getPointAtLength(len * t);
        точки.push({ x: p.x, y: p.y, t });
      }
      samplesRef.current = точки;
    } catch {
      /* jsdom и старые движки без геометрии — остаётся оценка */
    }
  }, [shape.code]);

  /* ── Видно ли кружок ─────────────────────────────────────── */
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    if (typeof IntersectionObserver !== "function") {
      setInView(true);
      return;
    }
    const io = new IntersectionObserver(
      (записи) => setInView(записи.some((з) => з.isIntersecting)),
      { threshold: 0.55 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  /* ── Немой цикл, пока кружок на экране ───────────────────── */
  useEffect(() => {
    const el = videoRef.current;
    if (!el || failed) return;
    if (!inView) {
      el.pause();
      return;
    }
    if (sound || бережно) return;
    el.muted = true;
    el.loop = true;
    // Автовоспроизведение могут запретить настройками — тогда просто постер
    el.play().catch(() => {});
  }, [inView, sound, failed, бережно]);

  const выключитьЗвук = useCallback(() => {
    releaseRef.current?.();
    releaseRef.current = null;
    setSound(false);
    const el = videoRef.current;
    if (!el) return;
    el.muted = true;
    el.loop = true;
    if (inViewRef.current && !бережно) el.play().catch(() => {});
    else el.pause();
  }, [бережно]);

  // Чужой звук отбирает наш — колбэк в claimPlayback живёт дольше рендера
  const stopRef = useRef(выключитьЗвук);
  stopRef.current = выключитьЗвук;

  useEffect(() => {
    const el = videoRef.current;
    if (!el) return;
    const onTime = () => {
      if (!scrubRef.current) setProgress(Math.min(1, el.currentTime / duration));
    };
    const onEnd = () => {
      setProgress(0);
      el.currentTime = 0;
      stopRef.current();
    };
    const onError = () => {
      setFailed(true);
      setSound(false);
    };
    el.addEventListener("timeupdate", onTime);
    el.addEventListener("ended", onEnd);
    el.addEventListener("error", onError);
    return () => {
      el.removeEventListener("timeupdate", onTime);
      el.removeEventListener("ended", onEnd);
      el.removeEventListener("error", onError);
      releaseRef.current?.();
      releaseRef.current = null;
    };
  }, [duration]);

  const включитьЗвук = () => {
    const el = videoRef.current;
    if (!el || failed) return;
    releaseRef.current?.();
    releaseRef.current = claimPlayback(() => stopRef.current());
    el.muted = false;
    el.loop = false;
    el.currentTime = 0;
    setProgress(0);
    setSound(true);
    el.play().catch(() => {
      setFailed(true);
      setSound(false);
    });
    if (unseen) {
      markPlayed(ключ);
      setUnseen(false);
    }
  };

  const переключить = () => {
    if (failed) return;
    haptic("light");
    if (sound) выключитьЗвук();
    else включитьЗвук();
  };

  /* ── Перемотка пальцем по контуру ────────────────────────── */

  /** Ближайшая точка контура к пальцу → доля пути. */
  const долиПоТочке = (clientX: number, clientY: number): number | null => {
    const box = boxRef.current;
    const точки = samplesRef.current;
    if (!box || точки.length === 0) return null;
    const r = box.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return null;
    const x = ((clientX - r.left) / r.width) * 100;
    const y = ((clientY - r.top) / r.height) * 100;
    let лучшая = точки[0];
    let мин = Infinity;
    for (const т of точки) {
      const d = (т.x - x) * (т.x - x) + (т.y - y) * (т.y - y);
      if (d < мин) {
        мин = d;
        лучшая = т;
      }
    }
    return лучшая.t;
  };

  /** Палец у края (внешняя треть радиуса) — это перемотка, а не тап. */
  const уКрая = (clientX: number, clientY: number): boolean => {
    const box = boxRef.current;
    if (!box) return false;
    const r = box.getBoundingClientRect();
    const dx = (clientX - (r.left + r.width / 2)) / (r.width / 2);
    const dy = (clientY - (r.top + r.height / 2)) / (r.height / 2);
    return Math.hypot(dx, dy) >= 0.62;
  };

  const применить = (доля: number) => {
    const el = videoRef.current;
    setProgress(доля);
    if (el && Number.isFinite(el.duration) && el.duration > 0) {
      el.currentTime = Math.min(el.duration - 0.05, доля * el.duration);
    }
  };

  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (failed || e.button !== 0) return;
    if (!уКрая(e.clientX, e.clientY)) return;
    const доля = долиПоТочке(e.clientX, e.clientY);
    if (доля === null) return;
    scrubRef.current = true;
    setScrubbing(true);
    e.currentTarget.setPointerCapture?.(e.pointerId);
    haptic("light");
    применить(доля);
  };

  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!scrubRef.current) return;
    const доля = долиПоТочке(e.clientX, e.clientY);
    if (доля !== null) применить(доля);
  };

  const onPointerUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!scrubRef.current) return;
    scrubRef.current = false;
    setScrubbing(false);
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    // После перемотки кружок продолжает как шёл — немо или со звуком
    videoRef.current?.play().catch(() => {});
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    const el = videoRef.current;
    if (!el || failed) return;
    const шаг = e.key === "ArrowRight" ? 3 : e.key === "ArrowLeft" ? -3 : 0;
    if (!шаг) return;
    e.preventDefault();
    const d = Number.isFinite(el.duration) && el.duration > 0 ? el.duration : duration;
    const t = Math.max(0, Math.min(d - 0.05, el.currentTime + шаг));
    el.currentTime = t;
    setProgress(t / d);
  };

  const остаток = Math.max(0, duration - progress * duration);
  const подпись = failed
    ? "Не открылось"
    : formatClock(sound || scrubbing ? остаток : duration);

  return (
    <div
      ref={boxRef}
      role="button"
      tabIndex={0}
      aria-label={
        failed
          ? "Видеосообщение не открылось"
          : sound
            ? "Свернуть видеосообщение"
            : `Видеосообщение, ${shape.title.toLowerCase()}, ${formatClock(duration)} — развернуть и включить звук`
      }
      onClick={переключить}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          переключить();
        } else onKeyDown(e);
      }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      // Метка для жеста «потянуть вправо → ответить» в ленте: у края кружка
      // палец перематывает запись, и свайп там перехватывать нельзя
      data-scrub="radial"
      className="relative block select-none cursor-pointer touch-none"
      style={{
        // В покое кружок компактный, со звуком — вырастает, как в Telegram:
        // в переписке он один из многих, а смотрят всегда один. Свернётся
        // сам — по концу записи и когда звук заберёт соседнее сообщение.
        width: sound ? РАЗВЁРНУТЫЙ : size,
        aspectRatio: "1 / 1",
        transition: "width 280ms cubic-bezier(0.22,1,0.36,1)",
      }}
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
          muted
          loop
          className="w-full h-full object-cover"
        />
        {/* Лёгкое затемнение у нижнего края — под плашку времени */}
        <span
          aria-hidden="true"
          className="absolute inset-x-0 bottom-0 h-1/3 pointer-events-none"
          style={{
            background:
              "linear-gradient(to top, rgba(0,0,0,0.34), rgba(0,0,0,0.10) 45%, transparent)",
          }}
        />
      </div>

      {/* Контур формы: тонкая подложка и поверх неё прогресс.
          Подложка — белая в треть силы у обоих собеседников. Своя была
          акцентной, и на своём же акцентном пузыре кружок выходил
          сиреневым по сиреневому: акцент перестаёт что-либо значить, если
          им покрашена и дорожка, и пройденная дуга. Акцент оставлен дуге. */}
      <svg
        viewBox="0 0 100 100"
        aria-hidden="true"
        className="absolute inset-0 w-full h-full pointer-events-none"
      >
        <path
          d={shape.d}
          fill="none"
          stroke="#ffffff"
          strokeOpacity={0.3}
          strokeWidth={2.2}
          vectorEffect="non-scaling-stroke"
        />
        <path
          d={shape.d}
          fill="none"
          stroke="var(--color-accent)"
          strokeWidth={sound || scrubbing ? 2.1 : 1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          ref={ringRef}
          strokeDasharray={ringLength}
          strokeDashoffset={ringLength * (1 - progress)}
          style={{
            // Немой цикл не должен тянуть взгляд обводкой — она проявляется
            // вместе со звуком
            opacity: sound || scrubbing ? 1 : 0.5,
            transition: scrubbing
              ? "none"
              : "stroke-dashoffset 0.25s linear, opacity 0.2s ease, stroke-width 0.2s ease",
          }}
        />
      </svg>

      {/* Динамик и время — внутри фигуры, у её нижнего края */}
      <span
        className="absolute -translate-x-1/2 -translate-y-1/2 pointer-events-none
                   flex items-center gap-1 pl-1.5 pr-2 py-[3px] rounded-full
                   text-[11px] font-medium tabular-nums text-white
                   ring-1 ring-white/15"
        style={{
          left: `${shape.anchor.x}%`,
          top: `${shape.anchor.y}%`,
          background: "rgba(0,0,0,0.46)",
          backdropFilter: "blur(6px)",
          WebkitBackdropFilter: "blur(6px)",
        }}
      >
        <svg width="13" height="13" viewBox="0 0 14 14" aria-hidden="true">
          <path d="M2.4 5.2h2.1L7.1 2.8v8.4L4.5 8.8H2.4z" fill="currentColor" />
          {sound ? (
            <path
              d="M9.1 4.6a3.2 3.2 0 0 1 0 4.8M10.9 3.1a5.4 5.4 0 0 1 0 7.8"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.2"
              strokeLinecap="round"
            />
          ) : (
            <path
              d="M9.3 5.1l3.2 3.8M12.5 5.1L9.3 8.9"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.2"
              strokeLinecap="round"
            />
          )}
        </svg>
        {подпись}
        {unseen && !failed && (
          <span
            className="w-[5px] h-[5px] rounded-full bg-accent"
            aria-label="не просмотрено"
          />
        )}
      </span>
    </div>
  );
}
