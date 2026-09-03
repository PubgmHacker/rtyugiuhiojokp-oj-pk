/**
 * Аудит действий админов: кто, что, с кем и когда сделал.
 *
 * Ответ на «почему этот человек забанен и кем» без опроса команды.
 * Журнал append-only и виден всем админам: взаимная видимость действий
 * в маленькой команде дисциплинирует лучше скрытого надзора.
 */

import { useState, useEffect, useCallback } from "react";
import { getAdminAudit, type AdminAuditEntry } from "../../lib/admin";

const ДЕЙСТВИЯ: Record<string, { label: string; tone: string }> = {
  ban: { label: "Бан", tone: "bg-danger/20 text-danger" },
  unban: { label: "Разбан", tone: "bg-success/20 text-success" },
  set_verified: { label: "Галочка", tone: "bg-info/20 text-info" },
  report_action: { label: "Жалоба", tone: "bg-warn/20 text-warn" },
  reel_action: { label: "Ролик", tone: "bg-accent/20 text-accent" },
  story_action: { label: "История", tone: "bg-accent/20 text-accent" },
  broadcast: { label: "Рассылка", tone: "bg-info/20 text-info" },
};

const ФИЛЬТРЫ: { id: string; label: string }[] = [
  { id: "all", label: "Все" },
  { id: "ban", label: "Баны" },
  { id: "unban", label: "Разбаны" },
  { id: "set_verified", label: "Галочки" },
  { id: "report_action", label: "Жалобы" },
  { id: "reel_action", label: "Ролики" },
  { id: "story_action", label: "Истории" },
  { id: "broadcast", label: "Рассылки" },
];

/** Параметры действия — в одну человеческую строку. */
function детали(e: AdminAuditEntry): string {
  const d = e.details;
  const части: string[] = [];
  if (typeof d.reason === "string" && d.reason) части.push(d.reason);
  if ("duration_hours" in d)
    части.push(d.duration_hours == null ? "навсегда" : `${d.duration_hours} ч`);
  if (typeof d.verified === "boolean")
    части.push(d.verified ? "выдана" : "снята");
  if (typeof d.outcome === "string") части.push(`итог: ${d.outcome}`);
  if (typeof d.note === "string" && d.note) части.push(d.note);
  if (typeof d.action === "string" && e.action === "reel_action")
    части.push(d.action === "hide" ? "скрыт" : "показан");
  if (typeof d.action === "string" && e.action === "story_action")
    части.push(d.action === "hide" ? "снята" : "показана");
  if (e.action === "broadcast") {
    if (typeof d.segment === "string")
      части.push(d.segment === "test" ? "тест — только себе" : "всем");
    if (typeof d.chars === "number") части.push(`${d.chars} симв.`);
  }
  return части.join(" · ");
}

export default function AuditTable() {
  const [entries, setEntries] = useState<AdminAuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [фильтр, setФильтр] = useState("all");
  const [page, setPage] = useState(1);
  // Сбой — не «Записей нет»: пустой журнал аудита при упавшей сети — ложь
  const [сбой, setСбой] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setСбой(false);
    try {
      setEntries(await getAdminAudit(фильтр, page, 50));
    } catch (e) {
      console.error(e);
      setСбой(true);
    } finally {
      setLoading(false);
    }
  }, [фильтр, page]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="bg-surface rounded-2xl overflow-hidden">
      <div className="flex gap-2 p-4 border-b border-white/5 overflow-x-auto no-scrollbar">
        {ФИЛЬТРЫ.map((f) => (
          <button
            key={f.id}
            onClick={() => { setФильтр(f.id); setPage(1); }}
            className={`px-3 py-1.5 rounded-xl text-sm whitespace-nowrap transition ${
              фильтр === f.id
                ? "bg-accent/20 text-accent"
                : "bg-bg text-text-muted hover:text-text"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-text-muted text-xs uppercase tracking-wider">
              <th className="px-4 py-3">Когда</th>
              <th className="px-4 py-3">Админ</th>
              <th className="px-4 py-3">Действие</th>
              <th className="px-4 py-3">Кого</th>
              <th className="px-4 py-3">Детали</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              [...Array(8)].map((_, i) => (
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
                  <p className="mb-3">Не удалось загрузить</p>
                  <button
                    onClick={load}
                    className="px-4 py-2 bg-bg rounded-xl text-sm font-medium hover:text-text transition"
                  >
                    Повторить
                  </button>
                </td>
              </tr>
            ) : entries.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-12 text-center text-text-muted">
                  Записей нет
                </td>
              </tr>
            ) : (
              entries.map((e) => {
                const вид = ДЕЙСТВИЯ[e.action] ?? {
                  label: e.action,
                  tone: "bg-white/5 text-text-muted",
                };
                return (
                  <tr key={e.id} className="border-t border-white/5">
                    <td className="px-4 py-3 text-text-muted text-xs whitespace-nowrap">
                      {e.created_at
                        ? new Date(e.created_at).toLocaleString("ru")
                        : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <p className="font-medium">{e.admin_name || "—"}</p>
                      <p className="text-xs text-text-muted">{e.admin_id.slice(0, 8)}…</p>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded-full whitespace-nowrap ${вид.tone}`}>
                        {вид.label}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {e.target_name || (e.target_user_id ? `${e.target_user_id.slice(0, 8)}…` : "—")}
                    </td>
                    <td className="px-4 py-3 text-text-muted max-w-[320px] truncate">
                      {детали(e) || "—"}
                    </td>
                  </tr>
                );
              })
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
            disabled={entries.length < 50}
            className="px-3 py-1 bg-bg rounded-lg text-sm disabled:opacity-30"
          >
            →
          </button>
        </div>
      </div>
    </div>
  );
}
