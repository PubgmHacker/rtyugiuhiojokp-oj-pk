import { useEffect, useState, useCallback } from "react";
import { useNavigate, Link } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Heart, X, Lock, Crown, ChevronRight } from "lucide-react";
import {
  getLikesReceived,
  likeProfile,
  type UserProfile,
  type MatchResponse,
} from "../lib/api";
import { useStore } from "../lib/store";
import { haptic } from "../lib/haptics";
import MatchModal from "../components/MatchModal";
import {
  ScreenHeader,
  EmptyState,
  Skeleton,
  Button,
  VerifiedBadge,
} from "../components/ui";

interface MatchData {
  partnerName: string;
  partnerPhoto?: string;
  score?: number;
  reason?: string;
  matchId?: string;
}

export default function Likes() {
  const navigate = useNavigate();
  const { setUnreadLikes, addMatch } = useStore();

  const [likes, setLikes] = useState<UserProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [matchData, setMatchData] = useState<MatchData | null>(null);

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
        <ScreenHeader title="Лайки" />
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
        <ScreenHeader title="Лайки" />
        <EmptyState
          emoji="📡"
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
        <ScreenHeader title="Лайки" />
        <EmptyState
          emoji="✨"
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
      <ScreenHeader
        title="Лайки"
        subtitle={`${likes.length} ${plural(likes.length, "человек", "человека", "человек")} ждут ответа`}
      />

      <p className="px-4 pt-3 text-[13.5px] text-text-muted">
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
            уже лайкнули вас. Узнайте, кто именно — в Plus
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
              <motion.article
                key={p.id}
                layout
                initial={{ opacity: 0, scale: 0.94 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                transition={{ type: "spring", stiffness: 380, damping: 34 }}
                className="relative aspect-[3/4] rounded-[var(--radius-tile)]
                           overflow-hidden bg-surface-2"
              >
              {p.photos?.[0] ? (
                <img
                  src={p.photos[0]}
                  alt={p.display_name}
                  loading="lazy"
                  decoding="async"
                  className="w-full h-full object-cover"
                />
              ) : (
                <div
                  className="w-full h-full flex items-center justify-center
                             text-4xl font-bold text-white/25"
                  style={{ background: "var(--gradient-placeholder)" }}
                >
                  {p.display_name?.[0]?.toUpperCase() ?? "?"}
                </div>
              )}

              <div className="absolute inset-0 bg-scrim pointer-events-none" />

              <div className="absolute inset-x-0 bottom-0 p-3">
                <div className="flex items-center gap-1 mb-2.5">
                  <span className="font-bold text-[15px] text-white truncate">
                    {p.display_name}
                    {p.age ? `, ${p.age}` : ""}
                  </span>
                  {p.is_verified && <VerifiedBadge size={13} />}
                </div>

                {/* Сообщение, приложенное к лайку: ради него и стоит открыть
                    этот экран — оно объясняет, почему вас лайкнули */}
                {p.like_message && (
                  <p
                    className="mb-2.5 px-2.5 py-1.5 rounded-[var(--radius-tile)]
                               glass-strong text-[12px] leading-snug text-white/90
                               line-clamp-3"
                  >
                    «{p.like_message}»
                  </p>
                )}

                <div className="flex gap-2">
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
                    className="flex-1 h-10 rounded-full bg-dawn text-white
                               flex items-center justify-center
                               disabled:opacity-40 active:scale-95 transition-transform"
                  >
                    <Heart size={18} fill="currentColor" />
                  </button>
                </div>
              </div>
            </motion.article>
            )
          )}
        </AnimatePresence>
      </div>

      <MatchModal data={matchData} onClose={() => setMatchData(null)} />
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
