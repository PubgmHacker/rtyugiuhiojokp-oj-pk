/**
 * Видео-лента: второй формат знакомства помимо свайпов.
 *
 * Вертикальная прокрутка с прилипанием (scroll-snap), играет только тот ролик,
 * что сейчас на экране: держать в памяти десяток играющих видео телефон не
 * может, а автозапуск всех сразу съедает трафик.
 *
 * Звук по умолчанию выключен: браузеры и iOS не дают автозапуск со звуком, а
 * лента, которая молча не играет, выглядит поломанной.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Heart, Plus, Trash2, Volume2, VolumeX, EyeOff } from "lucide-react";
import {
  deleteReel,
  getReels,
  toggleReelLike,
  type Reel,
} from "../lib/api";
import { haptic } from "../lib/haptics";
import { Button, EmptyState, ScreenHeader, Spinner } from "../components/ui";
import ReelUploader from "../components/ReelUploader";

export default function Reels() {
  const [reels, setReels] = useState<Reel[] | null>(null);
  const [before, setBefore] = useState<string | null>(null);
  const [exhausted, setExhausted] = useState(false);
  const [muted, setMuted] = useState(true);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [error, setError] = useState("");
  const loadingRef = useRef(false);

  const load = useCallback(
    async (cursor?: string | null) => {
      if (loadingRef.current) return;
      loadingRef.current = true;
      try {
        const page = await getReels(cursor);
        setReels((cur) => (cursor && cur ? [...cur, ...page.reels] : page.reels));
        setBefore(page.next_before ?? null);
        if (!page.reels.length) setExhausted(true);
      } catch {
        setError("Не удалось загрузить ленту");
        setReels((cur) => cur ?? []);
      } finally {
        loadingRef.current = false;
      }
    },
    []
  );

  useEffect(() => {
    load();
  }, [load]);

  const handleLike = useCallback(async (reel: Reel) => {
    haptic(reel.liked_by_me ? "light" : "success");
    // Меняем сразу, не дожидаясь сети: сердце должно откликаться на тап
    setReels((cur) =>
      (cur ?? []).map((r) =>
        r.id === reel.id
          ? {
              ...r,
              liked_by_me: !r.liked_by_me,
              likes_count: r.likes_count + (r.liked_by_me ? -1 : 1),
            }
          : r
      )
    );
    try {
      const fresh = await toggleReelLike(reel.id);
      setReels((cur) => (cur ?? []).map((r) => (r.id === fresh.id ? fresh : r)));
    } catch {
      // Откатываем: показывать лайк, которого нет на сервере, нельзя
      haptic("error");
      setReels((cur) =>
        (cur ?? []).map((r) =>
          r.id === reel.id
            ? {
                ...r,
                liked_by_me: reel.liked_by_me,
                likes_count: reel.likes_count,
              }
            : r
        )
      );
    }
  }, []);

  const handleDelete = useCallback(async (reel: Reel) => {
    if (!window.confirm("Удалить этот ролик?")) return;
    try {
      await deleteReel(reel.id);
      setReels((cur) => (cur ?? []).filter((r) => r.id !== reel.id));
      haptic("success");
    } catch {
      haptic("error");
      setError("Не удалось удалить ролик");
    }
  }, []);

  if (reels === null) {
    return (
      <div className="h-[calc(100dvh-68px)] flex items-center justify-center">
        <Spinner size={28} />
      </div>
    );
  }

  if (!reels.length) {
    return (
      <div>
        <ScreenHeader title="Видео" />
        <EmptyState
          emoji="🎬"
          title="Пока пусто"
          description="Снимите короткое видео — так на вас посмотрят живьём, а не по четырём фото."
          action={
            <Button size="lg" fullWidth onClick={() => setUploadOpen(true)}>
              <Plus size={18} />
              Записать первое
            </Button>
          }
        />
        <ReelUploader
          open={uploadOpen}
          onClose={() => setUploadOpen(false)}
          onDone={(reel) => setReels((cur) => [reel, ...(cur ?? [])])}
        />
      </div>
    );
  }

  return (
    <div className="relative h-[calc(100dvh-68px)]">
      <div
        className="h-full overflow-y-auto snap-y snap-mandatory no-scrollbar"
        onScroll={(e) => {
          const el = e.currentTarget;
          // Подгружаем за экран до конца, иначе виден рывок
          if (
            !exhausted &&
            el.scrollHeight - el.scrollTop - el.clientHeight < el.clientHeight
          ) {
            load(before);
          }
        }}
      >
        {reels.map((reel) => (
          <ReelItem
            key={reel.id}
            reel={reel}
            muted={muted}
            onLike={() => handleLike(reel)}
            onDelete={() => handleDelete(reel)}
          />
        ))}
      </div>

      {/* Управление поверх ленты */}
      <div className="absolute top-3 right-3 z-30 flex flex-col gap-2.5 safe-top">
        <button
          aria-label={muted ? "Включить звук" : "Выключить звук"}
          onClick={() => {
            haptic("light");
            setMuted((v) => !v);
          }}
          className="w-11 h-11 rounded-full glass-strong flex items-center justify-center
                     active:scale-95 transition-transform"
        >
          {muted ? <VolumeX size={19} /> : <Volume2 size={19} />}
        </button>
        <button
          aria-label="Записать видео"
          onClick={() => {
            haptic("light");
            setUploadOpen(true);
          }}
          className="w-11 h-11 rounded-full bg-dawn text-white flex items-center
                     justify-center active:scale-95 transition-transform"
        >
          <Plus size={20} />
        </button>
      </div>

      {error && (
        <button
          onClick={() => setError("")}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 z-30 px-4 py-2
                     rounded-full bg-danger/15 border border-danger/30
                     text-danger text-[13px] font-medium"
        >
          {error} · закрыть
        </button>
      )}

      <ReelUploader
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onDone={(reel) => setReels((cur) => [reel, ...(cur ?? [])])}
      />
    </div>
  );
}

/* ── Один ролик на весь экран ───────────────────────────────── */

function ReelItem({
  reel,
  muted,
  onLike,
  onDelete,
}: {
  reel: Reel;
  muted: boolean;
  onLike: () => void;
  onDelete: () => void;
}) {
  const ref = useRef<HTMLVideoElement | null>(null);

  // Играет только видимый ролик: десяток одновременно телефон не выдержит,
  // а трафик уйдёт на то, чего никто не смотрит
  useEffect(() => {
    const video = ref.current;
    if (!video) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          video.play().catch(() => {
            /* автозапуск может быть запрещён — не считаем это ошибкой */
          });
        } else {
          video.pause();
          video.currentTime = 0;
        }
      },
      { threshold: 0.6 }
    );
    observer.observe(video);
    return () => observer.disconnect();
  }, []);

  return (
    <section className="relative h-full w-full snap-start snap-always bg-black">
      <video
        ref={ref}
        src={reel.video_url}
        poster={reel.cover_url || undefined}
        muted={muted}
        loop
        playsInline
        preload="metadata"
        className="w-full h-full object-contain"
        onClick={() => {
          const video = ref.current;
          if (!video) return;
          if (video.paused) video.play().catch(() => {});
          else video.pause();
        }}
      />

      {/* Действия справа — тот же столбец, что и в свайп-ленте */}
      <div className="absolute right-3 bottom-32 z-20 flex flex-col items-center gap-4">
        <button
          aria-label={reel.liked_by_me ? "Убрать лайк" : "Лайк"}
          onClick={onLike}
          className="flex flex-col items-center gap-1 active:scale-90 transition-transform"
        >
          <span
            className={`w-12 h-12 rounded-full flex items-center justify-center
                        ${reel.liked_by_me ? "bg-dawn text-white" : "glass-strong"}`}
          >
            <Heart size={22} fill={reel.liked_by_me ? "currentColor" : "none"} />
          </span>
          {reel.likes_count > 0 && (
            <span className="text-[12px] font-semibold text-white/90">
              {reel.likes_count}
            </span>
          )}
        </button>

        {reel.is_mine && (
          <button
            aria-label="Удалить ролик"
            onClick={onDelete}
            className="w-11 h-11 rounded-full glass-strong flex items-center
                       justify-center text-danger active:scale-90 transition-transform"
          >
            <Trash2 size={18} />
          </button>
        )}
      </div>

      {/* Автор и подпись */}
      <div className="absolute inset-x-0 bottom-0 p-5 pb-8 pr-[80px] z-20 bg-scrim">
        {reel.is_hidden && (
          <p className="inline-flex items-center gap-1.5 mb-2 px-2.5 py-1 rounded-full
                        bg-warn/15 border border-warn/30 text-warn text-[12px] font-medium">
            <EyeOff size={12} />
            Снят с показа модерацией
          </p>
        )}

        <div className="flex items-center gap-2.5 mb-2">
          {reel.author_photo ? (
            <img
              src={reel.author_photo}
              alt=""
              loading="lazy"
              className="w-9 h-9 rounded-full object-cover ring-2 ring-white/20"
            />
          ) : (
            <span
              className="w-9 h-9 rounded-full flex items-center justify-center
                         text-[13px] font-bold text-white/50"
              style={{ background: "var(--gradient-placeholder)" }}
            >
              {reel.author_name?.[0]?.toUpperCase() ?? "?"}
            </span>
          )}
          <span className="font-bold text-[16px] text-white">
            {reel.author_name || "Без имени"}
            {reel.author_age ? `, ${reel.author_age}` : ""}
          </span>
        </div>

        {reel.caption && (
          <p className="text-[14px] leading-snug text-white/90 line-clamp-3">
            {reel.caption}
          </p>
        )}
      </div>
    </section>
  );
}
