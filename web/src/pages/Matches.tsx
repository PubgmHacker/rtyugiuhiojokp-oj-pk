import { useEffect, useState, useCallback } from "react";
import { useNavigate, Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Users, ChevronRight, Mic } from "lucide-react";
import { getMatches } from "../lib/api";
import { useStore } from "../lib/store";
import { haptic } from "../lib/haptics";
import { clearNotificationBadge } from "../lib/native";
import {
  ScreenHeader,
  EmptyState,
  Skeleton,
  Button,
  VerifiedBadge,
} from "../components/ui";

export default function Matches() {
  const navigate = useNavigate();
  const { matches, setMatches } = useStore();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    setError(false);
    try {
      setMatches(await getMatches());
      clearNotificationBadge();
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [setMatches]);

  useEffect(() => {
    load();
  }, [load]);

  const open = useCallback(
    (id: string) => {
      haptic("light");
      navigate(`/chat/${id}`);
    },
    [navigate]
  );

  // Пока переписки нет, мэтч живёт в верхней ленте: так виднее, кому
  // ещё стоит написать
  const fresh = matches.filter((m) => !m.last_message);
  const conversations = matches.filter((m) => m.last_message);

  if (loading) {
    return (
      <div>
        <ScreenHeader title="Чаты" />
        <div className="px-4 pt-4">
          <div className="flex gap-3.5 mb-7">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="w-16 h-16 rounded-full shrink-0" />
            ))}
          </div>
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="flex items-center gap-3 mb-4">
              <Skeleton className="w-14 h-14 rounded-full shrink-0" />
              <div className="flex-1">
                <Skeleton className="h-4 w-32 mb-2" />
                <Skeleton className="h-3 w-48" />
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <ScreenHeader title="Чаты" />
        <EmptyState
          emoji="📡"
          title="Нет связи"
          description="Не удалось загрузить список. Проверьте подключение к интернету."
          action={<Button onClick={load}>Повторить</Button>}
        />
      </div>
    );
  }

  if (!matches.length) {
    return (
      <div>
        <ScreenHeader title="Чаты" />
        <EmptyState
          emoji="💬"
          title="Пока пусто"
          description="Когда вы понравитесь друг другу, здесь появится чат. Начните с поиска."
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
        title="Чаты"
        subtitle={`${matches.length} ${plural(matches.length, "совпадение", "совпадения", "совпадений")}`}
      />

      {/* Комнаты по интересам: в общий чат написать проще, чем первым в личку,
          поэтому вход в них живёт рядом со списком переписок */}
      <Link
        to="/rooms"
        onClick={() => haptic("light")}
        className="mx-4 mt-3 flex items-center gap-3 px-4 py-3
                   rounded-[var(--radius-tile)] bg-surface-2 border border-hairline"
      >
        <Users size={18} className="text-accent shrink-0" />
        <span className="flex-1 text-[14.5px] font-semibold">
          Чаты по интересам
        </span>
        <ChevronRight size={17} className="text-text-faint shrink-0" />
      </Link>

      {/* Голосом знакомиться проще, чем текстом: голос сразу говорит о
          человеке больше, чем переписка */}
      <Link
        to="/voice"
        onClick={() => haptic("light")}
        className="mx-4 mt-2 flex items-center gap-3 px-4 py-3
                   rounded-[var(--radius-tile)] bg-surface-2 border border-hairline"
      >
        <Mic size={18} className="text-accent shrink-0" />
        <span className="flex-1 text-[14.5px] font-semibold">
          Голосовая рулетка
        </span>
        <ChevronRight size={17} className="text-text-faint shrink-0" />
      </Link>

      {/* ── Новые мэтчи ────────────────────────────────────── */}
      {fresh.length > 0 && (
        <section className="pt-4">
          <h2 className="px-4 text-caption text-text-muted mb-3">
            Новые совпадения
          </h2>
          <div className="flex gap-3.5 px-4 overflow-x-auto no-scrollbar pb-1">
            {fresh.map((m) => (
              <button
                key={m.id}
                onClick={() => open(m.id)}
                className="flex flex-col items-center gap-1.5 shrink-0 w-[70px]"
              >
                <Avatar
                  src={m.partner.photos?.[0]}
                  name={m.partner.display_name}
                  size={64}
                  ring
                />
                <span className="text-[12px] text-text-secondary truncate w-full text-center">
                  {m.partner.display_name}
                </span>
              </button>
            ))}
          </div>
        </section>
      )}

      {/* ── Переписки ──────────────────────────────────────── */}
      {conversations.length > 0 && (
        <section className="pt-6">
          <h2 className="px-4 text-caption text-text-muted mb-2">Сообщения</h2>
          <ul>
            {conversations.map((m, i) => (
              <motion.li
                key={m.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: Math.min(i * 0.03, 0.25) }}
              >
                <button
                  onClick={() => open(m.id)}
                  className="w-full flex items-center gap-3 px-4 py-3
                             active:bg-surface transition-colors text-left"
                >
                  <Avatar
                    src={m.partner.photos?.[0]}
                    name={m.partner.display_name}
                    size={56}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 mb-0.5">
                      <span className="font-semibold text-[15px] truncate">
                        {m.partner.display_name}
                      </span>
                      {m.partner.is_verified && <VerifiedBadge size={14} />}
                      {m.last_message_at && (
                        <span className="ml-auto text-[11.5px] text-text-faint shrink-0">
                          {formatTime(m.last_message_at)}
                        </span>
                      )}
                    </div>
                    <p
                      className={`text-[13.5px] truncate ${
                        m.unread_count ? "text-text font-medium" : "text-text-muted"
                      }`}
                    >
                      {m.last_message}
                    </p>
                  </div>
                  {!!m.unread_count && (
                    <span
                      className="min-w-[20px] h-5 px-1.5 rounded-full bg-dawn
                                 text-white text-[11px] font-bold
                                 flex items-center justify-center shrink-0"
                    >
                      {m.unread_count > 99 ? "99+" : m.unread_count}
                    </span>
                  )}
                </button>
              </motion.li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

/* ── Аватар с градиентной обводкой ──────────────────────────── */

function Avatar({
  src,
  name,
  size,
  ring,
}: {
  src?: string;
  name?: string;
  size: number;
  ring?: boolean;
}) {
  return (
    <div
      style={{ width: size, height: size }}
      className={`rounded-full overflow-hidden shrink-0 ${
        ring ? "ring-dawn" : "bg-surface-2"
      }`}
    >
      {src ? (
        <img
          src={src}
          alt=""
          loading="lazy"
          decoding="async"
          className="w-full h-full object-cover rounded-full"
        />
      ) : (
        <div
          className="w-full h-full rounded-full flex items-center justify-center
                     font-bold text-white/70"
          style={{ background: "var(--gradient-placeholder)", fontSize: size / 2.6 }}
        >
          {name?.[0]?.toUpperCase() ?? "?"}
        </div>
      )}
    </div>
  );
}

/** Сегодня — часы, вчера — «вчера», раньше — дата. */
function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";

  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  }

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return "вчера";

  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
}

function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}
