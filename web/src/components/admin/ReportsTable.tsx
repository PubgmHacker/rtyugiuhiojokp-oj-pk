import { useState, useEffect, useCallback } from "react";
import { AlertTriangle, CheckCircle, XCircle, Shield } from "lucide-react";
import { getAdminReports, resolveReport, type AdminReport } from "../../lib/admin";

const STATUS_MAP: Record<string, { label: string; color: string; icon: typeof AlertTriangle }> = {
  pending: { label: "Новая", color: "text-warn", icon: AlertTriangle },
  resolved: { label: "Решена", color: "text-success", icon: CheckCircle },
  dismissed: { label: "Отклонена", color: "text-text-muted", icon: XCircle },
};

// Набор обязан совпадать с REPORT_REASONS в api/models/schemas.py, иначе
// жалоба придёт без подписи и модератор не поймёт, на что смотрит
const REASON_MAP: Record<string, string> = {
  spam: "Спам",
  harassment: "Харассмент",
  nudity: "Контент 18+",
  scam: "Мошенничество",
  fake: "Чужие фото",
  underage: "Несовершеннолетний",
  drugs: "Наркотики",
  other: "Другое",
};

export default function ReportsTable() {
  const [reports, setReports] = useState<AdminReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("pending");
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  // Сбой — не «Нет жалоб»: успокаивающая галочка при упавшей сети опасна,
  // модератор решит, что очередь пуста, и уйдёт
  const [сбой, setСбой] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setСбой(false);
    try {
      const data = await getAdminReports(filter);
      setReports(data);
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

  const handleAction = async (reportId: string, action: "dismiss" | "resolve" | "ban_reported") => {
    setActionLoading(reportId);
    try {
      await resolveReport(reportId, action);
      setReports(reports.map((r) => (r.id === reportId ? { ...r, status: action === "dismiss" ? "dismissed" : "resolved" } : r)));
    } catch (e) {
      console.error(e);
    }
    setActionLoading(null);
  };

  return (
    <div className="bg-surface rounded-2xl overflow-hidden">
      {/* Filter tabs */}
      <div className="flex gap-2 p-4 border-b border-white/5 overflow-x-auto">
        {["pending", "all", "resolved", "dismissed"].map((s) => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            className={`px-4 py-1.5 rounded-full text-sm whitespace-nowrap transition ${
              filter === s ? "bg-accent text-on-accent" : "bg-bg text-text-muted hover:text-text"
            }`}
          >
            {s === "pending" ? "Новые" : s === "all" ? "Все" : s === "resolved" ? "Решённые" : "Отклонённые"}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-text-muted text-xs uppercase tracking-wider">
              <th className="px-4 py-3">Жалоба</th>
              <th className="px-4 py-3">От кого → На кого</th>
              <th className="px-4 py-3">Причина</th>
              <th className="px-4 py-3">Статус</th>
              <th className="px-4 py-3 hidden sm:table-cell">Дата</th>
              <th className="px-4 py-3 text-right">Действия</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              [...Array(5)].map((_, i) => (
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
            ) : reports.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center text-text-muted">
                  {filter === "pending" ? "Нет новых жалоб" : "Нет жалоб"}
                </td>
              </tr>
            ) : (
              reports.map((r) => {
                const st = STATUS_MAP[r.status] || STATUS_MAP.pending;
                const StIcon = st.icon;
                return (
                  <tr key={r.id} className="border-t border-white/5 hover:bg-white/[0.02] transition">
                    <td className="px-4 py-3">
                      <p className="font-medium truncate max-w-[200px]">
                        {REASON_MAP[r.reason] || r.reason}
                      </p>
                      {r.description && (
                        <p className="text-xs text-text-muted truncate max-w-[200px]">{r.description}</p>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <p className="text-xs">{r.reporter_name}</p>
                      <p className="text-xs text-text-muted">→ {r.reported_name}</p>
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-xs px-2 py-0.5 rounded-full bg-white/5 text-text-muted">
                        {r.reason}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1 text-xs ${st.color}`}>
                        <StIcon size={12} />
                        {st.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 hidden sm:table-cell text-text-muted text-xs">
                      {r.created_at ? new Date(r.created_at).toLocaleDateString("ru") : "—"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {r.status === "pending" && (
                        <div className="flex items-center justify-end gap-1">
                          <button
                            onClick={() => handleAction(r.id, "dismiss")}
                            disabled={actionLoading === r.id}
                            className="p-1.5 rounded-lg bg-white/5 text-text-muted hover:bg-white/10 transition disabled:opacity-40"
                            title="Отклонить"
                          >
                            <XCircle size={16} />
                          </button>
                          <button
                            onClick={() => handleAction(r.id, "resolve")}
                            disabled={actionLoading === r.id}
                            className="p-1.5 rounded-lg bg-success/10 text-success hover:bg-success/20 transition disabled:opacity-40"
                            title="Принять"
                          >
                            <CheckCircle size={16} />
                          </button>
                          <button
                            onClick={() => handleAction(r.id, "ban_reported")}
                            disabled={actionLoading === r.id}
                            className="p-1.5 rounded-lg bg-danger/10 text-danger hover:bg-danger/20 transition disabled:opacity-40"
                            title="Забанить нарушителя"
                          >
                            <Shield size={16} />
                          </button>
                        </div>
                      )}
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
