/**
 * Очередь верификации: кто застрял в живой проверке.
 *
 * Единственный ручной участок верификации. Кадры проверки — биометрия и не
 * хранятся, поэтому здесь фото анкеты и причины отказов AI, а решение —
 * «Выдать галочку» (та же ручка set-verified, что в карточке) для тех, кого
 * AI стабильно не узнаёт: шрам, гетерохромия, возрастные изменения.
 *
 * Статуса «разобрано» нет нарочно: очередь описывает реальность и
 * рассасывается сама — галочка выдана, проверка пройдена или попытки
 * ушли за окно.
 */

import { useState, useEffect, useCallback } from "react";
import { BadgeCheck } from "lucide-react";
import {
  getVerificationQueue,
  setUserVerified,
  type AdminVerificationQueueItem,
} from "../../lib/admin";
import UserCard from "./UserCard";

const ОКНА: { days: number; label: string }[] = [
  { days: 7, label: "Неделя" },
  { days: 14, label: "2 недели" },
  { days: 30, label: "Месяц" },
];

const ПРОВАЙДЕРЫ: Record<string, string> = {
  builtin: "Позы + AI",
  sumsub: "Sumsub",
};

export default function VerificationQueueTable() {
  const [items, setItems] = useState<AdminVerificationQueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(14);
  const [page, setPage] = useState(1);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  // Клик по строке открывает досье — решение о галочке требует контекста:
  // страйки, жалобы, прошлые баны
  const [openUserId, setOpenUserId] = useState<string | null>(null);
  // Сбой — не «Никто не застрял»: успокаивающая пустота при упавшей сети
  // прячет людей, которые ждут галочку
  const [сбой, setСбой] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setСбой(false);
    try {
      setItems(await getVerificationQueue(days, page, 50));
    } catch (e) {
      console.error(e);
      setСбой(true);
    } finally {
      setLoading(false);
    }
  }, [days, page]);

  useEffect(() => {
    load();
  }, [load]);

  const выдать = async (userId: string) => {
    if (!confirm("Выдать галочку вручную? Решение попадёт в журнал попыток и аудит.")) {
      return;
    }
    setActionLoading(userId);
    try {
      await setUserVerified(userId, true);
      // Верифицированный уходит из очереди — список честнее перезагрузить
      await load();
    } catch (e) {
      console.error(e);
      alert("Не получилось выдать галочку");
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <div className="bg-surface rounded-2xl overflow-hidden">
      <div className="flex gap-2 p-4 border-b border-white/5 overflow-x-auto no-scrollbar">
        {ОКНА.map((о) => (
          <button
            key={о.days}
            onClick={() => { setDays(о.days); setPage(1); }}
            className={`px-3 py-1.5 rounded-xl text-sm whitespace-nowrap transition ${
              days === о.days
                ? "bg-accent/20 text-accent"
                : "bg-bg text-text-muted hover:text-text"
            }`}
          >
            {о.label}
          </button>
        ))}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-text-muted text-xs uppercase tracking-wider">
              <th className="px-4 py-3">Человек</th>
              <th className="px-4 py-3">Отказы</th>
              <th className="px-4 py-3">Последний отказ</th>
              <th className="px-4 py-3">Когда</th>
              <th className="px-4 py-3 text-right">Действие</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              [...Array(6)].map((_, i) => (
                <tr key={i} className="border-t border-white/5">
                  {[...Array(5)].map((__, j) => (
                    <td key={j} className="px-4 py-3">
                      <div className="h-4 bg-bg rounded animate-pulse w-3/4" />
                    </td>
                  ))}
                </tr>
              ))
            ) : сбой ? (
              <tr>
                <td colSpan={5} className="px-4 py-12 text-center text-text-muted">
                  <p className="mb-3">📡 Не удалось загрузить</p>
                  <button
                    onClick={load}
                    className="px-4 py-2 bg-bg rounded-xl text-sm font-medium hover:text-text transition"
                  >
                    Повторить
                  </button>
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-12 text-center text-text-muted">
                  Никто не застрял в проверке
                </td>
              </tr>
            ) : (
              items.map((с) => (
                <tr
                  key={с.user_id}
                  onClick={() => setOpenUserId(с.user_id)}
                  className="border-t border-white/5 cursor-pointer hover:bg-white/[0.02]"
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      {с.photos[0] ? (
                        <img
                          src={с.photos[0]}
                          alt=""
                          className="w-10 h-10 rounded-lg object-cover shrink-0"
                        />
                      ) : (
                        <div className="w-10 h-10 rounded-lg bg-bg shrink-0" />
                      )}
                      <div>
                        <p className="font-medium">
                          {с.display_name || `${с.user_id.slice(0, 8)}…`}
                          {с.age != null && (
                            <span className="text-text-muted">, {с.age}</span>
                          )}
                        </p>
                        <p className="text-xs text-text-muted">{с.city || "—"}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <p className="font-medium text-danger">
                      {с.rejected_total} из {с.attempts_total} попыток
                    </p>
                    <p className="text-xs text-text-muted">
                      за сутки {с.rejected_24h} из {с.daily_limit}
                      {с.rejected_24h >= с.daily_limit && " — упёрся в лимит"}
                    </p>
                  </td>
                  <td className="px-4 py-3 max-w-[320px]">
                    <p className="truncate">{с.last_reason || "—"}</p>
                    <p className="text-xs text-text-muted">
                      {ПРОВАЙДЕРЫ[с.last_provider] ?? с.last_provider}
                    </p>
                  </td>
                  <td className="px-4 py-3 text-text-muted text-xs whitespace-nowrap">
                    {с.last_attempt_at
                      ? new Date(с.last_attempt_at).toLocaleString("ru")
                      : "—"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        выдать(с.user_id);
                      }}
                      disabled={actionLoading === с.user_id}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-info/10 text-info text-xs font-medium hover:bg-info/20 transition disabled:opacity-40"
                      title="Выдать галочку вручную — для тех, кого AI стабильно не узнаёт"
                    >
                      <BadgeCheck size={14} />
                      Выдать галочку
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between p-4 border-t border-white/5">
        <span className="text-xs text-text-muted">Страница {page}</span>
        <div className="flex gap-2">
          <button
            onClick={() => setPage(Math.max(1, page - 1))}
            disabled={page <= 1}
            className="px-3 py-1 bg-bg rounded-lg text-sm disabled:opacity-30"
          >
            ←
          </button>
          <button
            onClick={() => setPage(page + 1)}
            disabled={items.length < 50}
            className="px-3 py-1 bg-bg rounded-lg text-sm disabled:opacity-30"
          >
            →
          </button>
        </div>
      </div>

      {openUserId && (
        <UserCard
          userId={openUserId}
          onClose={() => setOpenUserId(null)}
          // Галочка или бан из карточки меняют состав очереди — перезагрузка
          onChanged={() => load()}
        />
      )}
    </div>
  );
}
