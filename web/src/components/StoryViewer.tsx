/**
 * Просмотрщик историй.
 *
 * Один счётчик времени на полосу прогресса и на автопереход: два
 * независимых таймера разъезжались бы после каждой паузы, и полоса
 * дозаполнялась бы уже на следующем кадре.
 *
 * Удержание ставит на паузу — на кадре с подписью пять секунд не хватает,
 * а перечитывать, гоняя историю по кругу, никто не станет.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Eye, MessageCircle, Trash2, X } from "lucide-react";
import { AuraRing } from "./Aura";
import { Sheet } from "./Sheet";
import { Spinner } from "./ui";
import { haptic } from "../lib/haptics";
import {
  deleteStory,
  getStoryReplyTarget,
  getStoryViewers,
  getUserStories,
  markStoryViewed,
  type Story,
  type StoryViewer as Зритель,
} from "../lib/api";

//: Сколько держим кадр. Пять секунд — столько нужно, чтобы рассмотреть
//: фотографию и прочитать короткую подпись, и не столько, чтобы устать.
const КАДР_МС = 5000;

export function StoryViewer({
  userId,
  onClose,
}: {
  userId: string;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const [stories, setStories] = useState<Story[]>([]);
  const [index, setIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);
  const [progress, setProgress] = useState(0);
  const [viewersOpen, setViewersOpen] = useState(false);
  const [viewers, setViewers] = useState<Зритель[]>([]);
  const [busy, setBusy] = useState(false);

  const прошло = useRef(0);
  const кадр = useRef<number | null>(null);
  const отмечено = useRef<Set<string>>(new Set());

  const story = stories[index];

  useEffect(() => {
    let живо = true;
    getUserStories(userId)
      .then((s) => {
        if (!живо) return;
        setStories(s);
        // Начинаем с первой непросмотренной: возвращать человека к
        // началу каждый раз — заставлять пролистывать уже виденное.
        const с = s.findIndex((x) => !x.seen);
        setIndex(с === -1 ? 0 : с);
      })
      .catch(() => живо && setError("Историй нет"))
      .finally(() => живо && setLoading(false));
    return () => {
      живо = false;
    };
  }, [userId]);

  const дальше = useCallback(() => {
    setIndex((i) => {
      if (i + 1 >= stories.length) {
        onClose();
        return i;
      }
      return i + 1;
    });
  }, [stories.length, onClose]);

  const назад = useCallback(() => {
    setIndex((i) => Math.max(0, i - 1));
  }, []);

  // Прогресс и переход — один цикл rAF. setInterval здесь давал бы
  // рывки при перерисовке, а на фоновой вкладке продолжал бы жечь кадры.
  useEffect(() => {
    прошло.current = 0;
    setProgress(0);
    if (!story) return;

    let last = performance.now();
    const шаг = (now: number) => {
      const dt = now - last;
      last = now;
      if (!paused) прошло.current += dt;

      const p = Math.min(1, прошло.current / КАДР_МС);
      setProgress(p);
      if (p >= 1) {
        дальше();
        return;
      }
      кадр.current = requestAnimationFrame(шаг);
    };
    кадр.current = requestAnimationFrame(шаг);

    return () => {
      if (кадр.current !== null) cancelAnimationFrame(кадр.current);
    };
  }, [story?.id, paused, дальше]);

  // Просмотр отмечаем один раз на кадр за сеанс: ручка идемпотентна, но
  // лишний запрос на каждое возвращение назад ничего не даёт.
  useEffect(() => {
    if (!story || story.mine || отмечено.current.has(story.id)) return;
    отмечено.current.add(story.id);
    markStoryViewed(story.id).catch(() => {});
  }, [story?.id, story?.mine]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") дальше();
      if (e.key === "ArrowLeft") назад();
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose, дальше, назад]);

  const открыть_зрителей = async () => {
    if (!story) return;
    haptic("light");
    setPaused(true);
    setViewersOpen(true);
    try {
      setViewers((await getStoryViewers(story.id)).viewers);
    } catch {
      setViewers([]);
    }
  };

  const ответить = async () => {
    if (!story || busy) return;
    setBusy(true);
    haptic("light");
    try {
      const { match_id, prefill } = await getStoryReplyTarget(story.id);
      onClose();
      navigate(`/chat/${match_id}`, { state: { prefill } });
    } catch (e: any) {
      setError(
        e?.response?.status === 403
          ? "Ответить можно только тому, с кем есть пара"
          : "Не получилось открыть переписку",
      );
      setBusy(false);
    }
  };

  const снять = async () => {
    if (!story || busy) return;
    setBusy(true);
    haptic("medium");
    try {
      await deleteStory(story.id);
      const остаток = stories.filter((s) => s.id !== story.id);
      if (!остаток.length) {
        onClose();
        return;
      }
      setStories(остаток);
      setIndex((i) => Math.min(i, остаток.length - 1));
    } catch {
      setError("Не удалось снять историю");
    } finally {
      setBusy(false);
    }
  };

  return (
    <motion.div
      className="fixed inset-0 z-[60] bg-black"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.16 }}
      drag="y"
      dragConstraints={{ top: 0, bottom: 0 }}
      dragElastic={{ top: 0, bottom: 0.5 }}
      onDragStart={() => setPaused(true)}
      onDragEnd={(_, info) => {
        if (info.offset.y > 110 || info.velocity.y > 620) onClose();
        else setPaused(false);
      }}
    >
      {loading ? (
        <div className="grid h-full place-items-center">
          <Spinner />
        </div>
      ) : error && !story ? (
        <div className="grid h-full place-items-center px-8 text-center">
          <p className="text-[15px] text-white/70">{error}</p>
        </div>
      ) : (
        story && (
          <>
            {/* Полосы прогресса. Пройденные залиты целиком — иначе
                непонятно, сколько кадров уже позади. */}
            <div className="safe-top absolute inset-x-0 top-0 z-20 flex gap-1 px-3 pt-2">
              {stories.map((s, i) => (
                <div
                  key={s.id}
                  className="h-[2.5px] flex-1 overflow-hidden rounded-full bg-white/25"
                >
                  <div
                    className="h-full rounded-full bg-white"
                    style={{
                      width:
                        i < index ? "100%" : i === index ? `${progress * 100}%` : "0%",
                      transition: i === index ? "none" : "width 160ms linear",
                    }}
                  />
                </div>
              ))}
            </div>

            <div className="safe-top absolute inset-x-0 top-0 z-20 flex items-center gap-2.5 px-3 pt-6">
              <AuraRing
                seed={story.user_id}
                src={null}
                name={story.display_name}
                size={34}
                ring={2}
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[14px] font-semibold text-white">
                  {story.display_name}
                </p>
                <p className="text-[11.5px] text-white/60">
                  {назад_во_времени(story.created_at)}
                </p>
              </div>
              <button
                onClick={onClose}
                aria-label="Закрыть"
                className="tap-target grid h-9 w-9 place-items-center rounded-full text-white/85"
              >
                <X size={22} />
              </button>
            </div>

            <AnimatePresence mode="wait">
              <motion.img
                key={story.id}
                src={story.media_url}
                alt=""
                className="h-full w-full object-contain"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.18 }}
              />
            </AnimatePresence>

            {/* Зоны касания. Левая треть — назад, остальное — вперёд:
                промах вперёд стоит дешевле промаха назад. */}
            <button
              aria-label="Предыдущий кадр"
              className="absolute inset-y-0 left-0 z-10 w-1/3"
              onClick={назад}
              onPointerDown={() => setPaused(true)}
              onPointerUp={() => setPaused(false)}
              onPointerCancel={() => setPaused(false)}
            />
            <button
              aria-label="Следующий кадр"
              className="absolute inset-y-0 right-0 z-10 w-2/3"
              onClick={дальше}
              onPointerDown={() => setPaused(true)}
              onPointerUp={() => setPaused(false)}
              onPointerCancel={() => setPaused(false)}
            />

            <div className="safe-bottom absolute inset-x-0 bottom-0 z-20 bg-scrim px-4 pb-4 pt-10">
              {story.caption && (
                <p className="mb-3 text-[15px] font-medium leading-snug text-white">
                  {story.caption}
                </p>
              )}

              {error && (
                <p className="mb-2 text-[13px] text-warn">{error}</p>
              )}

              {story.mine ? (
                <div className="flex items-center gap-2">
                  <button
                    onClick={открыть_зрителей}
                    className="flex flex-1 items-center justify-center gap-1.5 rounded-full bg-white/12 py-2.5 text-[14px] text-white backdrop-blur"
                  >
                    <Eye size={16} />
                    {story.views_count ?? 0} просмотров
                  </button>
                  <button
                    onClick={снять}
                    disabled={busy}
                    aria-label="Снять историю"
                    className="tap-target grid h-11 w-11 place-items-center rounded-full bg-white/12 text-white backdrop-blur disabled:opacity-50"
                  >
                    <Trash2 size={17} />
                  </button>
                </div>
              ) : (
                <button
                  onClick={ответить}
                  disabled={busy}
                  className="flex w-full items-center justify-center gap-1.5 rounded-full bg-white/12 py-2.5 text-[14px] text-white backdrop-blur disabled:opacity-50"
                >
                  <MessageCircle size={16} />
                  Ответить в переписке
                </button>
              )}
            </div>

            <Sheet
              open={viewersOpen}
              onClose={() => {
                setViewersOpen(false);
                setPaused(false);
              }}
              title="Кто смотрел"
            >
              {viewers.length === 0 ? (
                <p className="py-6 text-center text-[14px] text-text-muted">
                  Пока никто не открыл
                </p>
              ) : (
                <ul className="space-y-2.5 pb-2">
                  {viewers.map((v) => (
                    <li key={v.user_id} className="flex items-center gap-3">
                      <AuraRing
                        seed={v.user_id}
                        src={v.avatar}
                        name={v.display_name}
                        size={40}
                        bare
                      />
                      <span className="flex-1 truncate text-[15px] text-text">
                        {v.display_name}
                      </span>
                      <span className="text-[12px] text-text-faint">
                        {назад_во_времени(v.viewed_at)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Sheet>
          </>
        )
      )}
    </motion.div>
  );
}

/** «12 минут назад» — точное время у истории на сутки не нужно. */
function назад_во_времени(iso: string): string {
  const мин = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60000));
  if (мин < 1) return "только что";
  if (мин < 60) return `${мин} мин назад`;
  const ч = Math.floor(мин / 60);
  return `${ч} ч назад`;
}
