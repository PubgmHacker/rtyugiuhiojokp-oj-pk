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
import { AnimatePresence, motion } from "framer-motion";
import { askConfirm } from "../lib/telegram";
import {
  Heart, MessageCircle, Flag, Plus, Trash2, Volume2, VolumeX, EyeOff, Eye,
  Share2,
} from "lucide-react";
import {
  deleteReel,
  getReels,
  recordReelView,
  reportReel,
  toggleReelLike,
  type Reel,
} from "../lib/api";
import { haptic } from "../lib/haptics";
import { useSectionOpen } from "../lib/useSectionOpen";
import { Button, EmptyState, ScreenHeader, Spinner } from "../components/ui";
import ReelUploader from "../components/ReelUploader";
import ReelComments from "../components/ReelComments";
import ReelForwardSheet from "../components/ReelForwardSheet";
import { REPORT_REASONS } from "../lib/profileOptions";

export default function Reels() {
  useSectionOpen("reels");
  const [reels, setReels] = useState<Reel[] | null>(null);
  const [before, setBefore] = useState<string | null>(null);
  const [exhausted, setExhausted] = useState(false);
  const [muted, setMuted] = useState(true);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [commentsFor, setCommentsFor] = useState<Reel | null>(null);
  const [reportFor, setReportFor] = useState<Reel | null>(null);
  const [forwardFor, setForwardFor] = useState<Reel | null>(null);
  const [error, setError] = useState("");
  // Успех — своя плашка: «Отправлено» в красной рамке читается как сбой
  const [notice, setNotice] = useState("");
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

  const bumpComments = useCallback((reelId: string, delta: number) => {
    setReels((cur) =>
      (cur ?? []).map((r) =>
        r.id === reelId
          ? { ...r, comments_count: Math.max(0, r.comments_count + delta) }
          : r
      )
    );
    // Открытая шторка держит свою копию ролика — обновляем и её, иначе
    // счётчик в заголовке отстаёт на один
    setCommentsFor((cur) =>
      cur && cur.id === reelId
        ? { ...cur, comments_count: Math.max(0, cur.comments_count + delta) }
        : cur
    );
  }, []);

  const handleReport = useCallback(async (reel: Reel, reason: string) => {
    setReportFor(null);
    try {
      await reportReel(reel.id, reason);
      haptic("success");
      setError("Жалоба отправлена — модератор разберётся");
    } catch (e: any) {
      haptic("error");
      setError(e?.response?.data?.detail ?? "Не удалось отправить жалобу");
    }
  }, []);

  const handleDelete = useCallback(async (reel: Reel) => {
    if (!(await askConfirm("Удалить этот ролик?"))) return;
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
            onComments={() => setCommentsFor(reel)}
            onReport={() => setReportFor(reel)}
            onForward={() => setForwardFor(reel)}
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
          className="w-11 h-11 rounded-full bg-accent text-white flex items-center
                     justify-center active:scale-95 transition-transform"
        >
          <Plus size={20} />
        </button>
      </div>

      {notice && (
        <button
          onClick={() => setNotice("")}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 z-30 px-4 py-2
                     rounded-full bg-success/15 border border-success/30
                     text-success text-[13px] font-medium"
        >
          {notice} · закрыть
        </button>
      )}

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

      <ReelComments
        reel={commentsFor}
        onClose={() => setCommentsFor(null)}
        onCountChange={bumpComments}
      />

      <ReelReportSheet
        reel={reportFor}
        onClose={() => setReportFor(null)}
        onPick={(reason) => reportFor && handleReport(reportFor, reason)}
      />

      <ReelForwardSheet
        reel={forwardFor}
        onClose={() => setForwardFor(null)}
        onSent={(куда) => setNotice(`Отправлено: ${куда}`)}
      />
    </div>
  );
}

/* ── Выбор причины жалобы на ролик ──────────────────────────── */

function ReelReportSheet({
  reel,
  onClose,
  onPick,
}: {
  reel: Reel | null;
  onClose: () => void;
  onPick: (reason: string) => void;
}) {
  return (
    <AnimatePresence>
      {reel && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-black/60"
          />
          <motion.div
            role="dialog"
            aria-label="Причина жалобы"
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", stiffness: 380, damping: 36 }}
            className="fixed bottom-0 left-0 right-0 z-50 bg-bg-elevated
                       rounded-t-[var(--radius-sheet)] border-t border-hairline
                       px-5 pt-3 pb-7 safe-bottom max-h-[80dvh]
                       overflow-y-auto no-scrollbar"
          >
            <div className="w-10 h-1 rounded-full bg-surface-3 mx-auto mb-5" />

            <h2 className="text-heading font-bold mb-1.5">Пожаловаться на видео</h2>
            <p className="text-caption text-text-muted mb-4">
              Модератор посмотрит ролик. Три жалобы снимают его с показа сразу.
            </p>

            <div className="flex flex-col gap-1.5 mb-4">
              {REPORT_REASONS.map((r) => (
                <button
                  key={r.value}
                  onClick={() => onPick(r.value)}
                  className="w-full px-4 py-3 rounded-[var(--radius-tile)] text-left
                             bg-surface-2 border border-hairline text-[15px]
                             active:bg-surface transition-colors"
                >
                  {r.label}
                </button>
              ))}
            </div>

            <Button variant="secondary" size="lg" fullWidth onClick={onClose}>
              Отмена
            </Button>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

/* ── Один ролик на весь экран ───────────────────────────────── */

function ReelItem({
  reel,
  muted,
  onLike,
  onDelete,
  onComments,
  onReport,
  onForward,
}: {
  reel: Reel;
  muted: boolean;
  onLike: () => void;
  onDelete: () => void;
  onComments: () => void;
  onReport: () => void;
  onForward: () => void;
}) {
  const ref = useRef<HTMLVideoElement | null>(null);
  // Просмотр отмечаем один раз за монтирование: карточка перерисовывается на
  // каждый жест, и без этого один ролик давал бы десяток просмотров
  const viewSent = useRef(false);

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
          // Считаем просмотром то, что реально попало на экран, а не выдачу
          // ленты: она приходит на десяток роликов вперёд
          if (!viewSent.current && !reel.is_mine) {
            viewSent.current = true;
            recordReelView(reel.id);
          }
        } else {
          video.pause();
          video.currentTime = 0;
        }
      },
      { threshold: 0.6 }
    );
    observer.observe(video);
    return () => observer.disconnect();
  }, [reel.id, reel.is_mine]);

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
                        ${reel.liked_by_me ? "bg-accent text-white" : "glass-strong"}`}
          >
            <Heart size={22} fill={reel.liked_by_me ? "currentColor" : "none"} />
          </span>
          {reel.likes_count > 0 && (
            <span className="text-[12px] font-semibold text-white/90">
              {reel.likes_count}
            </span>
          )}
        </button>

        {/* Комментарии — то, ради чего лента вообще ведёт к знакомству:
            написать под видео проще, чем первым в личку */}
        <button
          aria-label="Комментарии"
          onClick={onComments}
          className="flex flex-col items-center gap-1 active:scale-90 transition-transform"
        >
          <span className="w-12 h-12 rounded-full glass-strong flex items-center justify-center">
            <MessageCircle size={21} />
          </span>
          {reel.comments_count > 0 && (
            <span className="text-[12px] font-semibold text-white/90">
              {reel.comments_count}
            </span>
          )}
        </button>

        {/* Переслать — следующее по частоте действие после реакции: ролик
            хочется показать конкретному человеку, а не лайкнуть в пустоту.
            Снятый модерацией ролик не пересылается — сервер откажет, и кнопку
            автору лучше не показывать вовсе */}
        {!reel.is_hidden && (
          <button
            aria-label="Переслать видео"
            onClick={onForward}
            className="w-11 h-11 rounded-full glass-strong flex items-center
                       justify-center active:scale-90 transition-transform"
          >
            <Share2 size={18} />
          </button>
        )}

        {/* На свой ролик жаловаться незачем, а на чужой — обязательно должно
            быть можно: это единственный публичный контент, откуда раньше
            нельзя было сообщить о нарушении */}
        {!reel.is_mine && (
          <button
            aria-label="Пожаловаться на ролик"
            onClick={onReport}
            className="w-11 h-11 rounded-full glass-strong flex items-center
                       justify-center text-warn active:scale-90 transition-transform"
          >
            <Flag size={17} />
          </button>
        )}

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

          {/* Просмотры показываем только автору: чужому зрителю эта цифра
              ничего не даёт, а автору говорит, работает ли ролик */}
          {reel.is_mine && reel.views_count > 0 && (
            <span className="flex items-center gap-1 text-[12px] text-white/60">
              <Eye size={12} />
              {reel.views_count}
            </span>
          )}
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
