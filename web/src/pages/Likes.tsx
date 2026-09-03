import { useEffect, useState, useCallback } from "react";
import { useNavigate, Link, useSearchParams } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  Heart,
  X,
  Lock,
  Crown,
  ChevronRight,
  MessageCircleHeart,
  Sparkles,
  WifiOff,
} from "lucide-react";
import {
  getLikesReceived,
  likeProfile,
  type UserProfile,
  type MatchResponse,
} from "../lib/api";
import { useStore } from "../lib/store";
import { haptic } from "../lib/haptics";
import MatchModal from "../components/MatchModal";
import DirectMessageSheet from "../components/DirectMessageSheet";
import PersonCard from "../components/PersonCard";
import ProfileSheet from "../components/ProfileSheet";
import Leaderboard from "../components/Leaderboard";
import {
  ScreenHeader,
  EmptyState,
  Skeleton,
  Button,
} from "../components/ui";

interface MatchData {
  partnerName: string;
  partnerPhoto?: string;
  score?: number;
  reason?: string;
  matchId?: string;
}

type Tab = "likes" | "top";

/**
 * Экран лайков с двумя видами: входящие симпатии и публичный топ по лайкам.
 *
 * Топ живёт здесь, а не отдельной вкладкой в навигации: он про то же самое —
 * кто кому нравится, — и своей вкладки не заслуживает.
 */
export default function Likes() {
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get("tab") === "top" ? "top" : "likes";
  const [tab, setTab] = useState<Tab>(requestedTab);

  useEffect(() => {
    setTab(requestedTab);
  }, [requestedTab]);

  return (
    <div>
      <ScreenHeader title="Лайки" />

      <div className="px-4 pt-1">
        <div className="flex p-1 chip">
          {(
            [
              ["likes", "Кто лайкнул"],
              ["top", "Топ недели"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              onClick={() => {
                haptic("select");
                setTab(value);
                setSearchParams(value === "top" ? { tab: "top" } : {});
              }}
              aria-pressed={tab === value}
              className={`flex-1 py-2 rounded-full text-[14px] font-semibold
                          transition-colors ${
                            tab === value ? "bg-accent text-white" : "text-text-secondary"
                          }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {tab === "likes" ? <IncomingLikes /> : <Leaderboard />}
    </div>
  );
}

function IncomingLikes() {
  const navigate = useNavigate();
  const { setUnreadLikes, addMatch } = useStore();

  const [likes, setLikes] = useState<UserProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [matchData, setMatchData] = useState<MatchData | null>(null);
  // Написать без взаимности тому, кто вас лайкнул, но кого вы ещё не оценили:
  // тоже платный крючок, отдельно от ответной симпатии
  const [directFor, setDirectFor] = useState<UserProfile | null>(null);
  // Полный профиль по тапу на карточку: решение «нравится / нет» не должно
  // приниматься по одному кадру (аудит, блок «Продукт»)
  const [viewed, setViewed] = useState<UserProfile | null>(null);

  const load = useCallback(async () => {
    setError(false);
    try {
      const data = await getLikesReceived();
      setLikes(data);
      setUnreadLikes(data.length);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [setUnreadLikes]);

  useEffect(() => {
    load();
  }, [load]);

  const respond = useCallback(
    async (profile: UserProfile, type: "like" | "pass") => {
      if (busyId) return;
      setBusyId(profile.id);

      // Убираем карточку сразу: ждать сеть на таком действии незачем
      setLikes((cur) => {
        const next = cur.filter((p) => p.id !== profile.id);
        setUnreadLikes(next.length);
        return next;
      });

      try {
        const result = await likeProfile(profile.id, type);
        if (result.matched && result.match) {
          haptic("success");
          setMatchData({
            partnerName: profile.display_name,
            partnerPhoto: profile.photos?.[0],
            score: result.match.match_score ?? undefined,
            reason: result.match.ai_reason ?? undefined,
            matchId: result.match.id,
          });
          addMatch(result.match as MatchResponse);
        } else {
          haptic(type === "like" ? "medium" : "light");
        }
      } catch {
        // Не получилось — возвращаем карточку, решение не должно пропасть
        haptic("error");
        setLikes((cur) => {
          const next = [profile, ...cur];
          setUnreadLikes(next.length);
          return next;
        });
      } finally {
        setBusyId(null);
      }
    },
    [busyId, addMatch, setUnreadLikes]
  );

  if (loading) {
    return (
      <div>
        <div className="grid grid-cols-2 gap-3 px-4 pt-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="aspect-[3/4]" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <EmptyState
          icon={WifiOff}
          title="Нет связи"
          description="Не удалось загрузить. Проверьте подключение к интернету."
          action={<Button onClick={load}>Повторить</Button>}
        />
      </div>
    );
  }

  if (!likes.length) {
    return (
      <div>
        <EmptyState
          icon={Sparkles}
          title="Пока никто"
          description="Здесь появятся те, кому вы понравились. Заполненная анкета с хорошим фото заметно ускоряет дело."
          action={
            <Button onClick={() => navigate("/discover")}>Смотреть анкеты</Button>
          }
        />
      </div>
    );
  }

  return (
    <div>
      <p className="px-4 pt-3 text-[13.5px] text-text-muted">
        {likes.length} {plural(likes.length, "человек", "человека", "человек")}{" "}
        {plural(likes.length, "ждёт", "ждут", "ждут")} ответа.{" "}
        Ответная симпатия сразу открывает чат.
      </p>

      {/* Кто именно лайкнул — платная возможность. Количество показываем
          честно всем: пустой экран заставил бы думать, что лайков нет */}
      {likes.some((p) => p.is_locked) && (
        <Link
          to="/plans"
          onClick={() => haptic("light")}
          className="mx-4 mt-3 flex items-center gap-3 px-4 py-3
                     rounded-[var(--radius-tile)] border border-accent/25 bg-accent/8"
        >
          <Crown size={18} className="text-accent shrink-0" />
          <span className="flex-1 text-[14px] leading-snug">
            <span className="font-bold">
              {likes.length} {plural(likes.length, "человек", "человека", "человек")}
            </span>{" "}
            уже {plural(likes.length, "лайкнул", "лайкнули", "лайкнули")} вас.
            Узнайте, кто именно — в Plus
          </span>
          <ChevronRight size={18} className="text-text-faint shrink-0" />
        </Link>
      )}

      <div className="grid grid-cols-2 gap-3 px-4 pt-3">
        <AnimatePresence mode="popLayout">
          {likes.map((p) =>
            p.is_locked ? (
              // Скрытая карточка: сервер не присылает ни имени, ни фото —
              // подглядеть в ответе API нечего
              <motion.article
                key={p.id}
                layout
                initial={{ opacity: 0, scale: 0.94 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                transition={{ type: "spring", stiffness: 380, damping: 34 }}
                className="relative aspect-[3/4] rounded-[var(--radius-tile)]
                           overflow-hidden border border-hairline"
                style={{ background: "var(--gradient-placeholder)" }}
              >
                <Link
                  to="/plans"
                  onClick={() => haptic("light")}
                  className="absolute inset-0 flex flex-col items-center justify-center gap-2"
                >
                  <Lock size={26} className="text-white/50" />
                  <span className="text-[12.5px] text-white/70 font-medium">
                    Открыть в Plus
                  </span>
                </Link>
              </motion.article>
            ) : (
              // Раскрытый лайк — та же стеклянная карточка человека, что и
              // всюду (PersonCard); тап по фото открывает полный профиль
              <motion.div
                key={p.id}
                layout
                initial={{ opacity: 0, scale: 0.94 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                transition={{ type: "spring", stiffness: 380, damping: 34 }}
                className="relative"
              >
                <button
                  aria-label={`Профиль ${p.display_name}`}
                  onClick={() => {
                    haptic("light");
                    setViewed(p);
                  }}
                  className="absolute inset-0 z-10 rounded-[var(--radius-tile)]"
                />
                <PersonCard profile={p} online={p.is_online}>
                  {/* Сообщение, приложенное к лайку: ради него и стоит открыть
                      этот экран — оно объясняет, почему вас лайкнули */}
                  {p.like_message && (
                    <p
                      className="mt-2.5 px-2.5 py-1.5 rounded-[var(--radius-tile)]
                                 glass-strong text-[12px] leading-snug text-white/90
                                 line-clamp-3"
                    >
                      «{p.like_message}»
                    </p>
                  )}

                  <div className="flex gap-2 mt-2.5 pointer-events-auto">
                    <button
                      aria-label={`Пропустить ${p.display_name}`}
                      disabled={busyId === p.id}
                      onClick={() => respond(p, "pass")}
                      className="flex-1 h-10 rounded-full glass-strong text-danger
                                 flex items-center justify-center
                                 disabled:opacity-40 active:scale-95 transition-transform"
                    >
                      <X size={19} strokeWidth={2.6} />
                    </button>
                    <button
                      aria-label={`Лайк ${p.display_name}`}
                      disabled={busyId === p.id}
                      onClick={() => respond(p, "like")}
                      className="flex-1 h-10 rounded-full bg-accent text-white
                                 flex items-center justify-center
                                 disabled:opacity-40 active:scale-95 transition-transform"
                    >
                      <Heart size={18} fill="currentColor" />
                    </button>
                    <button
                      aria-label={`Написать ${p.display_name} без лайка`}
                      disabled={busyId === p.id}
                      onClick={() => {
                        haptic("light");
                        setDirectFor(p);
                      }}
                      className="w-10 h-10 rounded-full glass-strong text-accent
                                 flex items-center justify-center shrink-0
                                 disabled:opacity-40 active:scale-95 transition-transform"
                    >
                      <MessageCircleHeart size={17} />
                    </button>
                  </div>
                </PersonCard>
              </motion.div>
            )
          )}
        </AnimatePresence>
      </div>

      <MatchModal data={matchData} onClose={() => setMatchData(null)} />
      <DirectMessageSheet profile={directFor} onClose={() => setDirectFor(null)} />

      {/* Полный профиль: решения те же, что на тайле, — человек не обязан
          возвращаться к сетке, чтобы ответить */}
      <ProfileSheet
        profile={viewed}
        onClose={() => setViewed(null)}
        actions={
          viewed && (
            <div className="flex gap-2.5">
              {/* Без aria-label: подпись и есть имя кнопки, а дубль тайловых
                  меток дал бы два одинаковых элемента для читалки */}
              <button
                disabled={busyId === viewed.id}
                onClick={() => {
                  const p = viewed;
                  setViewed(null);
                  respond(p, "pass");
                }}
                className="flex-1 h-12 chip
                           text-danger flex items-center justify-center gap-2
                           text-[15px] font-semibold
                           disabled:opacity-40 active:scale-95 transition-transform"
              >
                <X size={19} strokeWidth={2.6} />
                Пропустить
              </button>
              <button
                disabled={busyId === viewed.id}
                onClick={() => {
                  const p = viewed;
                  setViewed(null);
                  respond(p, "like");
                }}
                className="flex-1 h-12 rounded-full bg-accent text-white
                           flex items-center justify-center gap-2
                           text-[15px] font-semibold
                           disabled:opacity-40 active:scale-95 transition-transform"
              >
                <Heart size={18} fill="currentColor" />
                Лайк
              </button>
              <button
                aria-label="Написать письмо без лайка"
                disabled={busyId === viewed.id}
                onClick={() => {
                  const p = viewed;
                  haptic("light");
                  setViewed(null);
                  setDirectFor(p);
                }}
                className="w-12 h-12 chip
                           text-accent flex items-center justify-center shrink-0
                           disabled:opacity-40 active:scale-95 transition-transform"
              >
                <MessageCircleHeart size={18} />
              </button>
            </div>
          )
        }
      />
    </div>
  );
}

function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}
