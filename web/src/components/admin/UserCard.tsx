/**
 * Карточка пользователя — досье поверх таблицы.
 *
 * Разбор тикета это всегда одни и те же вопросы: кто это, платит ли, сколько
 * страйков и банов, что за жалобы, почему его не видно в деке. Карточка
 * отвечает на них одним экраном и тут же даёт действия: бан со сроком и
 * причиной, разбан, галочка. Быстрые кнопки в строке таблицы остаются для
 * бесспорных случаев.
 */

import { useState, useEffect, useCallback } from "react";
import {
  X, BadgeCheck, Shield, ShieldOff, RefreshCw,
} from "lucide-react";
import {
  getAdminUserCard,
  banUser,
  unbanUser,
  setUserVerified,
  type AdminUserCard,
} from "../../lib/admin";

interface Props {
  userId: string;
  onClose: () => void;
  /** Таблица подхватывает изменение строки без полной перезагрузки. */
  onChanged: (patch: { is_banned?: boolean; is_verified?: boolean }) => void;
}

/** Категории страйков — человеческими словами. Ключи из TEXT_STRIKE_RULES
 *  и content-страйков (api/services/enforcement.py). */
const СТРАЙКИ: Record<string, string> = {
  ad: "Реклама",
  heavy: "Тяжёлые нарушения",
  text: "Токсичный текст",
  content: "Контент, снятый по жалобам",
};

const СРОКИ_БАНА: { label: string; hours: number | null }[] = [
  { label: "24 часа", hours: 24 },
  { label: "3 суток", hours: 72 },
  { label: "7 суток", hours: 168 },
  { label: "Навсегда", hours: null },
];

function дата(iso: string | null | undefined, сВременем = false): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return сВременем ? d.toLocaleString("ru") : d.toLocaleDateString("ru");
}

function Строка({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3 py-1.5 text-sm">
      <span className="text-text-muted shrink-0">{label}</span>
      <span className="text-right">{children}</span>
    </div>
  );
}

function Секция({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-bg rounded-xl p-4">
      <h3 className="text-xs uppercase tracking-wider text-text-muted mb-2">{title}</h3>
      {children}
    </section>
  );
}

export default function UserCard({ userId, onClose, onChanged }: Props) {
  const [card, setCard] = useState<AdminUserCard | null>(null);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [срокБана, setСрокБана] = useState<number | null>(24);
  const [причина, setПричина] = useState("");

  const load = useCallback(async () => {
    setError(false);
    try {
      setCard(await getAdminUserCard(userId));
    } catch (e) {
      console.error(e);
      setError(true);
    }
  }, [userId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const действие = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
      // Перечитываем досье целиком: banned_until, амнистию страйков и запись
      // в журнале считает сервер, локальная правка тут же разошлась бы с ним
      await load();
    } catch (e) {
      console.error(e);
    } finally {
      setBusy(false);
    }
  };

  const забанить = () =>
    действие(async () => {
      await banUser(userId, причина, срокБана);
      onChanged({ is_banned: true });
    });

  const разбанить = () =>
    действие(async () => {
      await unbanUser(userId);
      onChanged({ is_banned: false });
    });

  const галочка = (verified: boolean) =>
    действие(async () => {
      await setUserVerified(userId, verified);
      onChanged({ is_verified: verified });
    });

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto
                 bg-black/60 p-4 sm:p-8"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl bg-surface rounded-2xl my-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Шапка */}
        <div className="flex items-start justify-between gap-3 p-4 border-b border-white/5">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="font-bold text-lg truncate">
                {card ? card.display_name || "Без анкеты" : "…"}
              </h2>
              {card?.is_verified && <BadgeCheck size={18} className="text-info" />}
              {card && (
                <span className={`text-xs px-2 py-0.5 rounded-full ${
                  card.role === "owner"
                    ? "bg-warn/20 text-warn"
                    : card.role === "admin"
                    ? "bg-accent/20 text-accent"
                    : "bg-white/5 text-text-muted"
                }`}>
                  {card.role}
                </span>
              )}
              {card && card.plan !== "free" && (
                <span className="text-xs px-2 py-0.5 rounded-full bg-warn/20 text-warn">
                  {card.plan}
                </span>
              )}
              {card?.is_banned && (
                <span className="text-xs px-2 py-0.5 rounded-full bg-danger/20 text-danger">
                  {card.banned_until
                    ? `забанен до ${дата(card.banned_until, true)}`
                    : "забанен навсегда"}
                </span>
              )}
            </div>
            {card && (
              <p className="text-xs text-text-muted mt-1 break-all">
                TG:{card.telegram_id ?? "—"} · {card.id} · язык {card.locale}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg bg-bg text-text-muted hover:text-text transition shrink-0"
            title="Закрыть"
          >
            <X size={18} />
          </button>
        </div>

        {error && (
          <div className="p-8 text-center">
            <p className="text-text-muted mb-3">Не удалось загрузить досье</p>
            <button
              onClick={load}
              className="inline-flex items-center gap-2 px-4 py-2 bg-bg rounded-xl text-sm"
            >
              <RefreshCw size={14} /> Повторить
            </button>
          </div>
        )}

        {!card && !error && (
          <div className="p-4 space-y-3">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-24 bg-bg rounded-xl animate-pulse" />
            ))}
          </div>
        )}

        {card && (
          <div className="p-4 space-y-3">
            {/* Фото — ссылками: модератору бывает нужен оригинал */}
            {card.photos.length > 0 && (
              <div className="flex gap-2 overflow-x-auto no-scrollbar">
                {card.photos.map((url) => (
                  <a key={url} href={url} target="_blank" rel="noreferrer" className="shrink-0">
                    <img
                      src={url}
                      alt=""
                      className="h-24 w-20 object-cover rounded-lg bg-bg"
                      loading="lazy"
                    />
                  </a>
                ))}
              </div>
            )}

            <div className="grid sm:grid-cols-2 gap-3">
              <Секция title="Анкета">
                <Строка label="Пол / возраст">
                  {card.gender === "male" ? "муж" : card.gender === "female" ? "жен" : "—"}
                  {card.age != null ? ` · ${card.age}` : ""}
                </Строка>
                <Строка label="Город">{card.city || "—"}</Строка>
                <Строка label="Видимость">
                  {card.is_incognito ? "инкогнито" : card.is_paused ? "на паузе" : "в деке"}
                </Строка>
                {card.bio && (
                  <p className="text-sm text-text-muted mt-1 line-clamp-3">{card.bio}</p>
                )}
                {card.interests.length > 0 && (
                  <p className="text-xs text-text-muted mt-1">
                    {card.interests.join(" · ")}
                  </p>
                )}
              </Секция>

              <Секция title="Аккаунт">
                <Строка label="Создан">{дата(card.created_at)}</Строка>
                <Строка label="Был в сети">{дата(card.last_seen_at, true)}</Строка>
                <Строка label="Привязки">
                  {[
                    card.telegram_id != null && "Telegram",
                    card.has_apple && "Apple",
                    card.has_email && "почта",
                  ]
                    .filter(Boolean)
                    .join(" · ") || "нет"}
                </Строка>
                <Строка label="Подписка">
                  {card.plan}
                  {card.plan_expires_at ? ` до ${дата(card.plan_expires_at)}` : ""}
                </Строка>
                <Строка label="Верификация">
                  {card.last_verification
                    ? `${card.last_verification.status} (${card.last_verification.provider})`
                    : "не проходил"}
                </Строка>
              </Секция>
            </div>

            <div className="grid grid-cols-5 gap-2 text-center">
              {[
                ["Пары", card.matches_count],
                ["Лайки →", card.likes_sent],
                ["Лайки ←", card.likes_received],
                ["Ролики", card.reels_count],
                ["Истории", card.stories_count],
              ].map(([label, n]) => (
                <div key={label as string} className="bg-bg rounded-xl py-2.5">
                  <p className="font-bold">{n}</p>
                  <p className="text-[11px] text-text-muted">{label}</p>
                </div>
              ))}
            </div>

            <Секция title="Модерация">
              {Object.entries(card.strikes).map(([key, s]) => (
                <Строка key={key} label={СТРАЙКИ[key] ?? key}>
                  <span className={s.count >= s.limit ? "text-danger font-semibold" : s.count > 0 ? "text-warn" : "text-text-muted"}>
                    {s.count} из {s.limit}
                  </span>
                  <span className="text-text-muted"> за {s.window_days} дн.</span>
                </Строка>
              ))}
              <Строка label="Прошлые баны (180 дн.)">
                <span className={card.prior_bans > 0 ? "text-warn" : "text-text-muted"}>
                  {card.prior_bans}
                </span>
              </Строка>
              <Строка label="Жалобы на него">
                {card.reports_against}
                {card.reports_pending > 0 && (
                  <span className="text-danger"> · {card.reports_pending} ждут</span>
                )}
              </Строка>
              <Строка label="Жалобы от него">{card.reports_by}</Строка>
            </Секция>

            {card.recent_moderation.length > 0 && (
              <Секция title="Журнал модерации — последние записи">
                <div className="space-y-2">
                  {card.recent_moderation.map((log) => (
                    <div key={log.id} className="text-xs flex gap-2 items-baseline">
                      <span className="text-text-muted shrink-0 w-24 truncate">
                        {log.content_type}
                      </span>
                      <span className={`px-1.5 py-0.5 rounded-full shrink-0 ${
                        log.result === "blocked"
                          ? "bg-danger/20 text-danger"
                          : log.result === "warning"
                          ? "bg-warn/20 text-warn"
                          : "bg-success/20 text-success"
                      }`}>
                        {log.result}
                      </span>
                      <span className="truncate flex-1">{log.content_preview || "—"}</span>
                      <span className="text-text-muted shrink-0">
                        {дата(log.created_at, true)}
                      </span>
                    </div>
                  ))}
                </div>
              </Секция>
            )}

            {/* Действия. Бан со сроком идёт мимо лестницы — админ решает сам */}
            <Секция title="Действия">
              <div className="flex flex-wrap items-center gap-2">
                <button
                  onClick={() => галочка(!card.is_verified)}
                  disabled={busy}
                  className={`inline-flex items-center gap-2 px-3 py-2 rounded-xl text-sm transition disabled:opacity-40 ${
                    card.is_verified
                      ? "bg-info/10 text-info hover:bg-info/20"
                      : "bg-white/5 text-text-muted hover:text-text"
                  }`}
                >
                  <BadgeCheck size={15} />
                  {card.is_verified ? "Снять галочку" : "Выдать галочку"}
                </button>

                {card.is_banned ? (
                  <button
                    onClick={разбанить}
                    disabled={busy}
                    className="inline-flex items-center gap-2 px-3 py-2 rounded-xl text-sm
                               bg-success/10 text-success hover:bg-success/20 transition disabled:opacity-40"
                  >
                    <ShieldOff size={15} />
                    Разбанить (снимет страйки)
                  </button>
                ) : ["admin", "owner"].includes(card.role) ? (
                  <span className="text-xs text-text-muted">
                    Админов и владельца банить нельзя
                  </span>
                ) : (
                  <>
                    <select
                      value={срокБана === null ? "forever" : String(срокБана)}
                      onChange={(e) =>
                        setСрокБана(e.target.value === "forever" ? null : Number(e.target.value))
                      }
                      disabled={busy}
                      className="px-3 py-2 bg-bg rounded-xl text-sm outline-none"
                    >
                      {СРОКИ_БАНА.map((s) => (
                        <option key={s.label} value={s.hours === null ? "forever" : String(s.hours)}>
                          {s.label}
                        </option>
                      ))}
                    </select>
                    <input
                      type="text"
                      value={причина}
                      onChange={(e) => setПричина(e.target.value)}
                      placeholder="Причина (увидит и бот)"
                      disabled={busy}
                      className="flex-1 min-w-[160px] px-3 py-2 bg-bg rounded-xl text-sm outline-none
                                 focus:ring-1 focus:ring-accent"
                    />
                    <button
                      onClick={забанить}
                      disabled={busy}
                      className="inline-flex items-center gap-2 px-3 py-2 rounded-xl text-sm
                                 bg-danger/10 text-danger hover:bg-danger/20 transition disabled:opacity-40"
                    >
                      <Shield size={15} />
                      Забанить
                    </button>
                  </>
                )}
              </div>
            </Секция>
          </div>
        )}
      </div>
    </div>
  );
}
