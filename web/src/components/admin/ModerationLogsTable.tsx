import { useState, useEffect, useCallback } from "react";
import { ShieldAlert, ShieldCheck, ShieldQuestion } from "lucide-react";
import { getModerationLogs, type AdminModerationLog } from "../../lib/admin";

const RESULT_COLORS: Record<string, { bg: string; text: string }> = {
  safe: { bg: "bg-success/10", text: "text-success" },
  warning: { bg: "bg-warn/10", text: "text-warn" },
  blocked: { bg: "bg-danger/10", text: "text-danger" },
};

export default function ModerationLogsTable() {
  const [logs, setLogs] = useState<AdminModerationLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  // Сбой — не «Нет записей модерации»: пустая таблица при упавшей сети — ложь
  const [сбой, setСбой] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setСбой(false);
    try {
      const data = await getModerationLogs(filter);
      setLogs(data);
    } catch (e) {
      console.error(e);
      setСбой(true);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="bg-surface rounded-2xl overflow-hidden">
      <div className="flex gap-2 p-4 border-b border-white/5">
        {["all", "blocked", "warning", "safe"].map((s) => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            className={`px-3 py-1.5 rounded-full text-xs transition ${
              filter === s ? "bg-accent text-on-accent" : "bg-bg text-text-muted hover:text-text"
            }`}
          >
            {s === "all" ? "Все" : s === "blocked" ? "Заблокировано" : s === "warning" ? "Предупреждения" : "Безопасно"}
          </button>
        ))}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-text-muted text-xs uppercase tracking-wider">
              <th className="px-4 py-3">Пользователь</th>
              <th className="px-4 py-3">Тип</th>
              <th className="px-4 py-3">Контент</th>
              <th className="px-4 py-3">Результат</th>
              <th className="px-4 py-3">Действие</th>
              <th className="px-4 py-3 hidden sm:table-cell">Дата</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              [...Array(8)].map((_, i) => (
                <tr key={i} className="border-t border-white/5">
                  {[...Array(6)].map((__, j) => (
                    <td key={j} className="px-4 py-3">
                      <div className="h-4 bg-bg rounded animate-pulse w-3/4" />
                    </td>
                  ))}
                </tr>
              ))
            ) : сбой ? (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center text-text-muted">
                  <p className="mb-3">Не удалось загрузить</p>
                  <button
                    onClick={load}
                    className="px-4 py-2 bg-bg rounded-xl text-sm font-medium hover:text-text transition"
                  >
                    Повторить
                  </button>
                </td>
              </tr>
            ) : logs.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center text-text-muted">
                  Нет записей модерации
                </td>
              </tr>
            ) : (
              logs.map((log) => {
                const rc = RESULT_COLORS[log.result] || RESULT_COLORS.safe;
                return (
                  <tr key={log.id} className="border-t border-white/5 hover:bg-white/[0.02]">
                    <td className="px-4 py-3">
                      <p className="font-medium text-xs">{log.user_name}</p>
                      <p className="text-xs text-text-muted">{log.user_id.slice(0, 8)}…</p>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${
                        log.content_type === "photo" ? "bg-accent/20 text-accent" : "bg-white/5 text-text-muted"
                      }`}>
                        {log.content_type === "photo" ? "Фото" : "Текст"}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <p className="text-xs truncate max-w-[200px]">{log.content_preview}</p>
                      {log.reason && (
                        <p className="text-xs text-text-muted truncate">{log.reason}</p>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${rc.bg} ${rc.text}`}>
                        {log.result}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs ${
                        log.action === "ban" ? "text-danger font-medium" :
                        log.action === "warn" ? "text-warn" : "text-text-muted"
                      }`}>
                        {log.action === "ban" ? "Бан" : log.action === "warn" ? "Предупреждение" : "—"}
                      </span>
                    </td>
                    <td className="px-4 py-3 hidden sm:table-cell text-text-muted text-xs">
                      {log.created_at ? new Date(log.created_at).toLocaleString("ru") : "—"}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
