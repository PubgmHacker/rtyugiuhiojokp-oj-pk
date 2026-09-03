/**
 * Лента историй — горизонтальная полоса над списком.
 *
 * Кольцо красим аурой автора: у всех приложений здесь одинаковый серый
 * кружок с фотографией, и различать людей приходится по снимку в 56
 * пикселей. Цвет узнаётся раньше, чем лицо.
 *
 * Просмотренные не убираем, а гасим кольцо: исчезающие элементы дёргают
 * полосу под пальцем, и человек теряет место, где остановился.
 */
import { useCallback, useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { AuraRing } from "./Aura";
import { StoryComposer } from "./StoryComposer";
import { StoryViewer } from "./StoryViewer";
import { useStore } from "../lib/store";
import { haptic } from "../lib/haptics";
import {
  getStoriesFeed,
  recordSectionOpen,
  type StoriesFeed,
  type StoryAuthor,
} from "../lib/api";

export function StoriesRail() {
  const user = useStore((s) => s.user);
  const [feed, setFeed] = useState<StoriesFeed>({ authors: [], mine: [] });
  const [loading, setLoading] = useState(true);
  const [composer, setComposer] = useState(false);
  //: Кого смотрим. null — просмотрщик закрыт.
  const [viewing, setViewing] = useState<string | null>(null);

  const загрузить = useCallback(async () => {
    try {
      // Ответ нормализуем: полоса висит над списком чатов, и один битый
      // ответ сервера (без mine или authors) не должен валить весь экран
      const свежая = await getStoriesFeed();
      setFeed({
        authors: Array.isArray(свежая?.authors) ? свежая.authors : [],
        mine: Array.isArray(свежая?.mine) ? свежая.mine : [],
      });
    } catch {
      // Молча: полоса историй не имеет права ломать экран, на котором
      // висит. Пусто — значит пусто.
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    загрузить();
    const onFocus = () =>
      document.visibilityState === "visible" && загрузить();
    document.addEventListener("visibilitychange", onFocus);
    return () => document.removeEventListener("visibilitychange", onFocus);
  }, [загрузить]);

  const есть_свои = feed.mine.length > 0;

  // Пока пусто и своих нет — полосу не показываем совсем. Пустая лента с
  // одной кнопкой «+» занимает место и не объясняет, зачем она.
  if (loading || (!есть_свои && feed.authors.length === 0)) return null;

  const открыть = (userId: string) => {
    haptic("light");
    // Считаем открытие истории, а не показ полосы: полоса висит над списком
    // чатов постоянно, и монтирование говорило бы лишь о заходе в чаты.
    recordSectionOpen("stories");
    setViewing(userId);
  };

  return (
    <>
      <div className="no-scrollbar flex gap-3.5 overflow-x-auto px-4 py-3">
        {/* Своя история всегда первая: это и вход в публикацию, и место,
            где человек проверяет, что выложилось. */}
        <button
          onClick={() => (есть_свои ? открыть(user!.id) : (haptic("light"), setComposer(true)))}
          className="flex w-16 shrink-0 flex-col items-center gap-1.5"
        >
          <span className="relative">
            <AuraRing
              seed={user?.id || "me"}
              src={user?.photos?.[0] || null}
              name={user?.display_name}
              size={60}
              bare={!есть_свои}
              dim={false}
            />
            <span
              onClick={(e) => {
                e.stopPropagation();
                haptic("light");
                setComposer(true);
              }}
              className="absolute -bottom-0.5 -right-0.5 grid h-5 w-5 place-items-center rounded-full border-2 border-bg bg-accent text-on-accent"
            >
              <Plus size={12} strokeWidth={3} />
            </span>
          </span>
          <span className="w-full truncate text-center text-[11.5px] text-text-muted">
            {есть_свои ? "Моя" : "Добавить"}
          </span>
        </button>

        {feed.authors
          .filter((a) => a.user_id !== user?.id)
          .map((a: StoryAuthor) => (
            <button
              key={a.user_id}
              onClick={() => открыть(a.user_id)}
              className="flex w-16 shrink-0 flex-col items-center gap-1.5"
            >
              <AuraRing
                seed={a.user_id}
                src={a.avatar}
                name={a.display_name}
                size={60}
                dim={!a.has_unseen}
              />
              <span
                className={`w-full truncate text-center text-[11.5px] ${
                  a.has_unseen ? "text-text" : "text-text-faint"
                }`}
              >
                {a.display_name}
              </span>
            </button>
          ))}
      </div>

      <StoryComposer
        open={composer}
        onClose={() => setComposer(false)}
        onPublished={() => загрузить()}
      />

      {viewing && (
        <StoryViewer
          userId={viewing}
          onClose={() => {
            setViewing(null);
            // Перечитываем: кольца просмотренных должны погаснуть сразу,
            // иначе человек возвращается к той же яркой полосе.
            загрузить();
          }}
        />
      )}
    </>
  );
}
