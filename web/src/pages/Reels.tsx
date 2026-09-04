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

import { useCallback, useEffect, useRef, useState, type UIEvent } from "react";
import { askConfirm } from "../lib/telegram";
import { letterAvatarStyle } from "../lib/aura";
import {
  Heart,
  MessageCircle,
  Flag,
  Plus,
  Trash2,
  Volume2,
  VolumeX,
  EyeOff,
  Eye,
  Share2,
  Clapperboard,
  MoreHorizontal,
  Send,
} from "lucide-react";
import {
  deleteReel,
  getReels,
  recordReelView,
  reportReel,
  toggleReelLike,
  type Reel,
} from "../lib/api";
import { assertList } from "../lib/payload";
import { haptic } from "../lib/haptics";
import { useSectionOpen } from "../lib/useSectionOpen";
import { Button, EmptyState, LoadError, ScreenHeader, Spinner } from "../components/ui";
import ReelUploader from "../components/ReelUploader";
import ReelComments from "../components/ReelComments";
import ReelForwardSheet from "../components/ReelForwardSheet";
import ReportReasonSheet from "../components/ReportReasonSheet";
import DirectMessageSheet from "../components/DirectMessageSheet";
import { Sheet } from "../components/Sheet";
import { SettingsGroup, SettingsRow } from "../components/SettingsRows";

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
  // Меню «ещё» — редкие действия (жалоба, удаление, письмо автору) живут в
  // шторке, как в TikTok и Instagram: столбик справа остаётся из трёх кнопок
  const [menuFor, setMenuFor] = useState<Reel | null>(null);
  const [directFor, setDirectFor] = useState<Reel | null>(null);
  const [error, setError] = useState("");
  // Успех — своя плашка: «Отправлено» в красной рамке читается как сбой
  const [notice, setNotice] = useState("");
  const [сбой, setСбой] = useState(false);
  const loadingRef = useRef(false);
  const scrollFrameRef = useRef<number | null>(null);

  const load = useCallback(
    async (cursor?: string | null) => {
      if (loadingRef.current) return;
      loadingRef.current = true;
      try {
        const page = await getReels(cursor);
        const items = assertList<Reel>(page.reels, "reels");
        setReels((cur) => (cursor && cur ? [...cur, ...items] : items));
        const nextBefore = page.next_before ?? null;
        setBefore(nextBefore);
        // Последняя непустая страница тоже заканчивается без курсора. Иначе
        // следующий scroll вызывает load(null) и заменяет ленту первой
        // страницей вместо завершения пагинации.
        if (!items.length || !nextBefore) setExhausted(true);
      } catch {
        if (cursor) {
          // Догрузка следующей страницы: лента на месте, хватит плашки
          setError("Не удалось загрузить ленту");
        } else {
          // Первая загрузка: пустую ленту подставлять нельзя — «Пока пусто»
          // с кнопкой «Записать первое» при упавшей сети — ложь
          setСбой(true);
        }
      } finally {
        loadingRef.current = false;
      }
    },
    []
  );

  useEffect(() => {
    load();
    return () => {
      if (scrollFrameRef.current !== null) {
        cancelAnimationFrame(scrollFrameRef.current);
        scrollFrameRef.current = null;
      }
    };
  }, [load]);

  const handleScroll = useCallback(
    (event: UIEvent<HTMLDivElement>) => {
      if (scrollFrameRef.current !== null) return;
      const element = event.currentTarget;
      scrollFrameRef.current = requestAnimationFrame(() => {
        scrollFrameRef.current = null;
        if (
          !exhausted &&
          element.scrollHeight - element.scrollTop - element.clientHeight <
            element.clientHeight
        ) {
          void load(before);
        }
      });
    },
    [before, exhausted, load]
  );

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
      // Зелёная плашка, не красная: успех в error-канале читался как сбой
      setNotice("Жалоба отправлена — модератор разберётся");
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
    if (сбой) {
      return (
        <div>
          <ScreenHeader title="Видео" />
          <LoadError
            onRetry={() => {
              setСбой(false);
              load();
            }}
          />
        </div>
      );
    }
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
          icon={Clapperboard}
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
    /* Полотно на весь экран под плавающим таб-баром, как в TikTok: видео
       уходит под стекло бара, а подпись и действия стоят над ним (--nav-h).
       Шторки вынесены из полотна: внутри fixed-контейнера с z-index они
       оказались бы под таб-баром, у которого z-40 в общем контексте. */
    <>
    <div className="reels-stage fixed inset-0 z-30 bg-black text-white">
      <div
        className="h-full overflow-y-auto snap-y snap-mandatory no-scrollbar"
        onScroll={handleScroll}
      >
        {reels.map((reel) => (
          <ReelItem
            key={reel.id}
            reel={reel}
            muted={muted}
            onLike={() => handleLike(reel)}
            onComments={() => setCommentsFor(reel)}
            onForward={() => setForwardFor(reel)}
            onMore={() => {
              haptic("light");
              setMenuFor(reel);
            }}
          />
        ))}
      </div>

      {/* Шапка поверх ленты: название слева, звук и запись справа */}
      <div className="absolute inset-x-0 top-0 z-30 safe-top pointer-events-none">
        <div className="flex items-center justify-between px-4 pt-2">
          <h1 className="text-[20px] font-extrabold tracking-[-0.02em] reel-shadow">
            Видео
          </h1>
          <div className="flex items-center gap-2 pointer-events-auto">
            <button
              aria-label={muted ? "Включить звук" : "Выключить звук"}
              onClick={() => {
                haptic("light");
                setMuted((v) => !v);
              }}
              className="w-10 h-10 rounded-full bg-white/12 backdrop-blur-md flex items-center
                         justify-center active:scale-95 transition-transform"
            >
              {muted ? <VolumeX size={18} /> : <Volume2 size={18} />}
            </button>
            <button
              aria-label="Записать видео"
              onClick={() => {
                haptic("light");
                setUploadOpen(true);
              }}
              className="h-10 pl-3 pr-3.5 rounded-full bg-white text-black flex items-center gap-1.5
                         text-[14px] font-semibold active:scale-95 transition-transform"
            >
              <Plus size={18} />
              Снять
            </button>
          </div>
        </div>
      </div>

      {notice && (
        <button
          onClick={() => setNotice("")}
          className="absolute left-1/2 -translate-x-1/2 z-30 px-4 py-2 rounded-full
                     bg-success/20 backdrop-blur-md border border-success/40
                     text-white text-[13px] font-medium"
          style={{ bottom: "calc(var(--nav-h) + 12px)" }}
        >
          {notice} · закрыть
        </button>
      )}

      {error && (
        <button
          onClick={() => setError("")}
          className="absolute left-1/2 -translate-x-1/2 z-30 px-4 py-2 rounded-full
                     bg-danger/25 backdrop-blur-md border border-danger/45
                     text-white text-[13px] font-medium"
          style={{ bottom: "calc(var(--nav-h) + 12px)" }}
        >
          {error} · закрыть
        </button>
      )}

    </div>

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

      {/* Меню ролика: строки того же стека, что и настройки */}
      <Sheet
        open={menuFor !== null}
        onClose={() => setMenuFor(null)}
        title={menuFor ? menuFor.author_name || "Ролик" : undefined}
        subtitle={menuFor?.caption || undefined}
      >
        {menuFor && (
          <SettingsGroup>
            {!menuFor.is_mine && (
              <SettingsRow
                icon={Send}
                title="Написать без лайка"
                hint="Личное сообщение автору ролика"
                onClick={() => {
                  const r = menuFor;
                  setMenuFor(null);
                  setDirectFor(r);
                }}
              />
            )}
            {!menuFor.is_hidden && (
              <SettingsRow
                icon={Share2}
                title="Переслать"
                hint="Показать ролик тому, с кем уже общаетесь"
                onClick={() => {
                  const r = menuFor;
                  setMenuFor(null);
                  setForwardFor(r);
                }}
              />
            )}
            {!menuFor.is_mine && (
              <SettingsRow
                icon={Flag}
                title="Пожаловаться"
                hint="Модератор посмотрит ролик"
                onClick={() => {
                  const r = menuFor;
                  setMenuFor(null);
                  setReportFor(r);
                }}
              />
            )}
            {menuFor.is_mine && (
              <SettingsRow
                icon={Trash2}
                title="Удалить ролик"
                tone="danger"
                chevron={false}
                onClick={() => {
                  const r = menuFor;
                  setMenuFor(null);
                  handleDelete(r);
                }}
              />
            )}
          </SettingsGroup>
        )}
      </Sheet>

      <DirectMessageSheet
        profile={
          directFor
            ? { id: directFor.author_id, display_name: directFor.author_name || "Автор" }
            : null
        }
        onClose={() => setDirectFor(null)}
        onSent={() => setNotice("Сообщение отправлено")}
      />

      <ReportReasonSheet
        open={reportFor !== null}
        title="Пожаловаться на видео"
        subtitle="Модератор посмотрит ролик. Три жалобы снимают его с показа сразу."
        onClose={() => setReportFor(null)}
        onPick={(reason) => reportFor && handleReport(reportFor, reason)}
      />

      <ReelForwardSheet
        reel={forwardFor}
        onClose={() => setForwardFor(null)}
        onSent={(куда) => setNotice(`Отправлено: ${куда}`)}
      />
    </>
  );
}

/* ── Один ролик на весь экран ───────────────────────────────── */

function ReelItem({
  reel,
  muted,
  onLike,
  onComments,
  onForward,
  onMore,
}: {
  reel: Reel;
  muted: boolean;
  onLike: () => void;
  onComments: () => void;
  onForward: () => void;
  onMore: () => void;
}) {
  const ref = useRef<HTMLVideoElement | null>(null);
  const [videoState, setVideoState] = useState<"loading" | "ready" | "error">(
    "loading"
  );
  // Вертикальный ролик заполняет экран, горизонтальный — вписывается целиком:
  // резать людей по краям нельзя, а чёрные поля у портретного видео выглядят
  // как поломанный плеер
  const [fit, setFit] = useState<"cover" | "contain">("cover");
  const [progress, setProgress] = useState(0);
  const [paused, setPaused] = useState(false);
  const [burst, setBurst] = useState(0);
  // Просмотр отмечаем один раз за монтирование: карточка перерисовывается на
  // каждый жест, и без этого один ролик давал бы десяток просмотров
  const viewSent = useRef(false);
  const lastTap = useRef(0);
  const tapTimer = useRef<number | null>(null);

  // Играет только видимый ролик: десяток одновременно телефон не выдержит,
  // а трафик уйдёт на то, чего никто не смотрит
  useEffect(() => {
    const video = ref.current;
    if (!video) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setPaused(false);
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
          setProgress(0);
        }
      },
      { threshold: 0.6 }
    );
    observer.observe(video);
    return () => {
      observer.disconnect();
      if (tapTimer.current) window.clearTimeout(tapTimer.current);
    };
  }, [reel.id, reel.is_mine]);

  // Один тап — пауза, два подряд — лайк: жесты TikTok, к которым все привыкли
  const handleTap = () => {
    const now = Date.now();
    if (now - lastTap.current < 280) {
      lastTap.current = 0;
      if (tapTimer.current) {
        window.clearTimeout(tapTimer.current);
        tapTimer.current = null;
      }
      setBurst((n) => n + 1);
      if (!reel.liked_by_me) onLike();
      return;
    }
    lastTap.current = now;
    tapTimer.current = window.setTimeout(() => {
      tapTimer.current = null;
      const video = ref.current;
      if (!video) return;
      if (video.paused) {
        video.play().catch(() => {});
        setPaused(false);
      } else {
        video.pause();
        setPaused(true);
      }
    }, 280);
  };

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
        aria-label={`Видео ${reel.author_name || "автора"}`}
        className={`w-full h-full ${fit === "cover" ? "object-cover" : "object-contain"}`}
        onLoadedMetadata={(e) => {
          const v = e.currentTarget;
          if (v.videoWidth && v.videoHeight) {
            setFit(v.videoHeight >= v.videoWidth ? "cover" : "contain");
          }
        }}
        onTimeUpdate={(e) => {
          const v = e.currentTarget;
          if (v.duration) setProgress(v.currentTime / v.duration);
        }}
        onLoadStart={() => setVideoState("loading")}
        onCanPlay={() => setVideoState("ready")}
        onPlaying={() => setVideoState("ready")}
        onWaiting={() => setVideoState("loading")}
        onStalled={() => setVideoState("loading")}
        onError={() => setVideoState("error")}
        onClick={handleTap}
      />

      {/* Сердце по двойному тапу */}
      {burst > 0 && (
        <span
          key={burst}
          aria-hidden="true"
          className="reel-burst absolute inset-0 z-10 grid place-items-center pointer-events-none"
        >
          <Heart size={96} fill="currentColor" className="text-white drop-shadow-lg" />
        </span>
      )}

      {paused && videoState !== "error" && (
        <span
          aria-hidden="true"
          className="absolute inset-0 z-10 grid place-items-center pointer-events-none"
        >
          <span className="w-16 h-16 rounded-full bg-black/35 backdrop-blur-sm grid place-items-center">
            <span className="ml-1 border-y-[14px] border-l-[22px] border-y-transparent border-l-white/90" />
          </span>
        </span>
      )}

      {videoState === "loading" && !paused && (
        <div
          role="status"
          aria-live="polite"
          className="absolute inset-0 z-10 flex items-center justify-center pointer-events-none"
        >
          <Spinner size={24} />
          <span className="sr-only">Видео загружается</span>
        </div>
      )}
      {videoState === "error" && (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-black/55 px-8 text-center">
          <p role="alert" className="text-[14px] text-white">
            Видео не удалось загрузить
          </p>
          <button
            type="button"
            className="rounded-full bg-white/15 px-4 py-2 text-[13px] text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
            onClick={() => {
              const video = ref.current;
              if (!video) return;
              setVideoState("loading");
              video.load();
              video.play().catch(() => {});
            }}
          >
            Повторить
          </button>
        </div>
      )}

      {/* Низ: слева автор и подпись, справа столбик действий. Оба стоят над
          плавающим таб-баром — как в TikTok, где бар накрывает само видео */}
      <div
        className="absolute inset-x-0 bottom-0 z-20 bg-scrim pointer-events-none"
        style={{ paddingBottom: "calc(var(--nav-h) + 10px)" }}
      >
        <div className="flex items-end gap-3 px-4">
          <div className="flex-1 min-w-0 pointer-events-auto">
            {reel.is_hidden && (
              <p className="inline-flex items-center gap-1.5 mb-2 px-2.5 py-1 rounded-full
                            bg-warn/20 border border-warn/40 text-white text-[12px] font-medium">
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
                  className="w-10 h-10 rounded-full object-cover ring-2 ring-white/80"
                />
              ) : (
                <span
                  className="w-10 h-10 rounded-full flex items-center justify-center
                             text-[14px] font-bold ring-2 ring-white/80"
                  style={letterAvatarStyle(reel.author_id)}
                >
                  {reel.author_name?.[0]?.toUpperCase() ?? "?"}
                </span>
              )}
              <div className="min-w-0">
                <p className="font-bold text-[16px] leading-tight text-white reel-shadow truncate">
                  {reel.author_name || "Без имени"}
                  {reel.author_age ? `, ${reel.author_age}` : ""}
                </p>
                {/* Просмотры показываем только автору: чужому зрителю эта цифра
                    ничего не даёт, а автору говорит, работает ли ролик */}
                {reel.is_mine && (
                  <p className="flex items-center gap-1 text-[12px] text-white/75 reel-shadow">
                    <Eye size={12} />
                    {reel.views_count} просмотров
                  </p>
                )}
              </div>
            </div>

            {reel.caption && (
              <p className="text-[14px] leading-snug text-white/95 line-clamp-3 reel-shadow">
                {reel.caption}
              </p>
            )}
          </div>

          {/* Столбик TikTok/Instagram: плоские белые значки с тенью и числом под
              каждым, без стеклянных кружков — так их читают все */}
          {/* w-16, а не w-12: подпись «Отправить» шире числовых и на 48px вылезала
                из столбика — на 390px она упиралась в самый край экрана */}
          <div className="flex flex-col items-center gap-[18px] pb-1 w-16 shrink-0 pointer-events-auto">
            <button
              aria-label={reel.liked_by_me ? "Убрать лайк" : "Лайк"}
              aria-pressed={reel.liked_by_me}
              onClick={onLike}
              className="reel-action"
            >
              <Heart
                size={30}
                strokeWidth={1.9}
                fill={reel.liked_by_me ? "currentColor" : "none"}
                className={reel.liked_by_me ? "text-accent" : ""}
              />
              <span>{сокр(reel.likes_count)}</span>
            </button>

            {/* Комментарии — то, ради чего лента вообще ведёт к знакомству:
                написать под видео проще, чем первым в личку */}
            <button aria-label="Комментарии" onClick={onComments} className="reel-action">
              <MessageCircle size={30} strokeWidth={1.9} />
              <span>{сокр(reel.comments_count)}</span>
            </button>

            {/* Снятый модерацией ролик не пересылается — сервер откажет */}
            {!reel.is_hidden && (
              <button aria-label="Переслать видео" onClick={onForward} className="reel-action">
                <Share2 size={28} strokeWidth={1.9} />
                <span>Отправить</span>
              </button>
            )}

            <button aria-label="Ещё действия" onClick={onMore} className="reel-action">
              <MoreHorizontal size={28} strokeWidth={2} />
            </button>
          </div>
        </div>

        {/* Прогресс ролика — тонкая линия над таб-баром, как в TikTok */}
        <div className="mx-4 mt-3 h-[2px] rounded-full bg-white/20 overflow-hidden">
          <div
            className="h-full bg-white/90"
            style={{ width: `${Math.round(progress * 1000) / 10}%` }}
          />
        </div>
      </div>
    </section>
  );
}

/** 12 400 → «12,4K»: длинные числа под значком не помещаются и ломают столбик */
function сокр(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, "")}K`;
  return n > 0 ? String(n) : "";
}
