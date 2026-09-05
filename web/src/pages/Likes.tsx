import { useEffect, useState, useCallback } from "react";
import { useNavigate, Link, useSearchParams } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  Heart,
  X,
  Lock,
  Crown,
  ChevronRight,
  Quote,
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
        <div className="grid grid-cols-3 gap-2 px-4 pt-4">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="aspect-[3/4] rounded-[14px]" />
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

  const hidden = likes.filter((p) => p.is_locked).length;

  return (
    <div>
      <p className="px-4 pt-3 text-[13.5px] text-text-muted">
        {likes.length} {plural(likes.length, "человек", "человека", "человек")}{" "}
        {plural(likes.length, "ждёт", "ждут", "ждут")} ответа
      </p>

      {/* Кто именно лайкнул — платная возможность. Количество показываем
          честно всем: пустой экран заставил бы думать, что лайков нет */}
      {hidden > 0 && (
        <Link
          to="/plans"
          onClick={() => haptic("light")}
          className="mx-4 mt-3 flex items-center gap-3 px-4 py-3
                     rounded-[var(--radius-tile)] border border-accent/25 bg-accent/8"
        >
          <Crown size={18} className="text-accent shrink-0" />
          <span className="flex-1 text-[14px] leading-snug">
            {hidden < likes.length && "Ещё "}
            <span className="font-bold">
              {hidden} {plural(hidden, "человек", "человека", "человек")}
            </span>{" "}
            {plural(hidden, "лайкнул", "лайкнули", "лайкнули")} вас. Кто именно — покажет Plus
          </span>
          <ChevronRight size={18} className="text-text-faint shrink-0" />
        </Link>
      )}

      {/* Три в ряд: экран отвечает на лайки, а не рассматривает анкеты —
          рассматривать открывают полный профиль тапом. Мелкий тайл держит
          только имя, возраст и два решения; всё остальное — в шторке.
          Один-два лайка сетка на три колонки не держит: тайл в углу и две
          трети пустоты выглядели как обрыв загрузки, поэтому на малом числе
          колонок столько же, сколько людей. */}
      <div
        className={`grid gap-2 px-4 pt-3 ${
          likes.length === 1
            ? "grid-cols-1 max-w-[58%] mx-auto"
            : likes.length === 2
              ? "grid-cols-2"
              : "grid-cols-3"
        }`}
      >
        <AnimatePresence mode="popLayout">
          {likes.map((p) =>
            p.is_locked ? (
              <LockedTile key={p.id} />
            ) : (
              <LikeTile
                key={p.id}
                profile={p}
                busy={busyId === p.id}
                onOpen={() => {
                  haptic("light");
                  setViewed(p);
                }}
                onPass={() => respond(p, "pass")}
                onLike={() => respond(p, "like")}
              />
            )
          )}
        </AnimatePresence>
      </div>

      {/* Конец списка. Без него сетка обрывается, и под ней остаётся полэкрана
          черноты — на двух лайках это читается как «дальше не загрузилось».
          Строка отвечает на единственный вопрос, который тут возникает: где
          взять ещё. Тихо — накопительный призыв уже стоит выше, у платной
          строки, и два акцентных блока на экране спорили бы друг с другом. */}
      <Link
        to="/discover"
        onClick={() => haptic("light")}
        className="mx-4 mt-6 flex items-center gap-3 glass-soft rounded-[16px] px-4 py-3.5
                   active:scale-[0.99] transition-transform"
      >
        <Sparkles size={18} className="shrink-0 text-text-muted" />
        <p className="flex-1 text-[13px] leading-relaxed text-text-muted">
          Это все, кто ждёт ответа. Новые лайки приходят из ленты — там анкеты,
          которые вас ещё не видели.
        </p>
        <ChevronRight size={18} className="shrink-0 text-text-faint" />
      </Link>

      <MatchModal data={matchData} onClose={() => setMatchData(null)} />

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
                className="flex-1 h-12 rounded-full chip
                           text-text flex items-center justify-center gap-2
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
                className="flex-[1.4] h-12 rounded-full liquid-primary
                           flex items-center justify-center gap-2
                           text-[15px] font-semibold
                           disabled:opacity-40 active:scale-95 transition-transform"
              >
                <Heart size={18} fill="currentColor" />
                Лайк
              </button>
            </div>
          )
        }
      />
    </div>
  );
}

/* ── Тайлы сетки ─────────────────────────────────────────────── */

interface TileProps {
  profile: UserProfile;
  busy: boolean;
  onOpen: () => void;
  onPass: () => void;
  onLike: () => void;
}

const TILE_SPRING = { type: "spring", stiffness: 380, damping: 34 } as const;

/**
 * Раскрытый лайк. Фото на весь тайл, имя с возрастом и два решения жидким
 * стеклом на самом фото: пропуск — прозрачный, лайк — единственное цветное
 * пятно на экране, как и в деке. Письмо, приложенное к лайку, здесь только
 * помечено значком кавычек: текст целиком — в профиле по тапу, в тайле
 * шириной в треть экрана он читался бы построчно.
 */
function LikeTile({ profile: p, busy, onOpen, onPass, onLike }: TileProps) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.92 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.85, y: -10 }}
      transition={TILE_SPRING}
      className="relative"
    >
      <button
        aria-label={`Профиль ${p.display_name}`}
        onClick={onOpen}
        className="absolute inset-0 z-10 rounded-[14px]"
      />
      <PersonCard
        profile={p}
        size="mini"
        badge={
          p.like_message ? (
            <span
              aria-label="С сообщением"
              className="w-6 h-6 rounded-full liquid liquid-photo flex items-center justify-center"
            >
              <Quote size={11} strokeWidth={2.4} fill="currentColor" />
            </span>
          ) : undefined
        }
      >
        <div className="flex items-center justify-center gap-2 mt-2 pointer-events-auto">
          <button
            aria-label={`Пропустить ${p.display_name}`}
            disabled={busy}
            onClick={onPass}
            className="w-9 h-9 rounded-full liquid liquid-photo
                       flex items-center justify-center
                       disabled:opacity-40 active:scale-90 transition-transform"
          >
            <X size={16} strokeWidth={2.6} />
          </button>
          <button
            aria-label={`Лайк ${p.display_name}`}
            disabled={busy}
            onClick={onLike}
            className="w-9 h-9 rounded-full liquid-primary
                       flex items-center justify-center
                       disabled:opacity-40 active:scale-90 transition-transform"
          >
            <Heart size={15} fill="currentColor" strokeWidth={0} />
          </button>
        </div>
      </PersonCard>
    </motion.div>
  );
}

/**
 * Скрытый лайк бесплатного уровня. Сервер не присылает ни имени, ни фото —
 * подглядеть в ответе API нечего, так что тайл честно пустой: мягкий градиент
 * вместо лица и замок в стекле. Тап ведёт на подписку.
 */
function LockedTile() {
  return (
    <motion.article
      layout
      initial={{ opacity: 0, scale: 0.92 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.85 }}
      transition={TILE_SPRING}
      className="relative aspect-[3/4] rounded-[14px] overflow-hidden liked-locked"
    >
      <Link
        to="/plans"
        onClick={() => haptic("light")}
        className="absolute inset-0 flex flex-col items-center justify-center gap-2"
      >
        <span className="w-10 h-10 rounded-full liquid liquid-photo flex items-center justify-center">
          <Lock size={16} strokeWidth={2.2} />
        </span>
        <span className="text-[11.5px] text-white/80 font-semibold tracking-[-0.01em]">
          Открыть в Plus
        </span>
      </Link>
    </motion.article>
  );
}

function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}
