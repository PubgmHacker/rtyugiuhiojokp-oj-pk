import { useState, useEffect, useCallback } from "react";
import { LayoutDashboard, Users, AlertTriangle, ShieldCheck, LayoutGrid, LogOut } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { getAdminStats, type AdminStats } from "../lib/admin";
import { useStore } from "../lib/store";
import StatCards from "../components/admin/StatCards";
import RegistrationsChart from "../components/admin/RegistrationsChart";
import UsersTable from "../components/admin/UsersTable";
import ReportsTable from "../components/admin/ReportsTable";
import ModerationLogsTable from "../components/admin/ModerationLogsTable";
import SectionsTable from "../components/admin/SectionsTable";

type Tab = "overview" | "users" | "reports" | "moderation" | "sections";

const TABS: { id: Tab; label: string; icon: typeof Users }[] = [
  { id: "overview", label: "Обзор", icon: LayoutDashboard },
  { id: "users", label: "Пользователи", icon: Users },
  { id: "reports", label: "Жалобы", icon: AlertTriangle },
  { id: "moderation", label: "Модерация", icon: ShieldCheck },
  { id: "sections", label: "Разделы", icon: LayoutGrid },
];

export default function AdminDashboard() {
  const navigate = useNavigate();
  const { user, logout } = useStore();
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<Tab>("overview");

  const loadStats = useCallback(async () => {
    try {
      const data = await getAdminStats();
      setStats(data);
    } catch (e) {
      console.error("Failed to load stats:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStats();
    // Refresh stats every 60s
    const interval = setInterval(loadStats, 60000);
    return () => clearInterval(interval);
  }, [loadStats]);

  // Guard: only admin/owner
  if (user && user.role && !["admin", "owner"].includes(user.role)) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <p className="text-2xl mb-2">🔒</p>
          <p className="text-text-muted">Доступ только для администраторов</p>
        </div>
      </div>
    );
  }

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  return (
    <div className="min-h-screen">
      {/* Top bar */}
      <header className="sticky top-0 z-30 bg-bg/95 backdrop-blur-lg border-b border-surface safe-top">
        <div className="max-w-7xl mx-auto flex items-center justify-between px-4 py-3">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-dawn flex items-center justify-center">
              <span className="text-white font-bold">SD</span>
            </div>
            <div>
              <h1 className="font-bold text-sm">Admin Panel</h1>
              <p className="text-xs text-text-muted">Souldawn Dating</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-text-muted hidden sm:block">
              {user?.display_name || "Admin"}
            </span>
            <button
              onClick={handleLogout}
              className="p-2 rounded-lg bg-surface text-text-muted hover:text-danger transition"
              title="Выйти"
            >
              <LogOut size={18} />
            </button>
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 py-6">
        {/* Tabs */}
        <div className="flex gap-2 mb-6 overflow-x-auto no-scrollbar">
          {TABS.map((t) => {
            const isActive = tab === t.id;
            const badge = t.id === "reports" && stats?.pending_reports ? stats.pending_reports : 0;
            return (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium whitespace-nowrap transition ${
                  isActive
                    ? "bg-dawn text-white"
                    : "bg-surface text-text-muted hover:text-text"
                }`}
              >
                <t.icon size={16} />
                {t.label}
                {badge > 0 && (
                  <span className={`px-1.5 py-0.5 rounded-full text-xs ${
                    isActive ? "bg-white/20" : "bg-danger/20 text-danger"
                  }`}>
                    {badge}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* Content */}
        {tab === "overview" && (
          <div className="space-y-6">
            <StatCards stats={stats} loading={loading} />
            <RegistrationsChart stats={stats} />
            {stats && stats.pending_reports > 0 && (
              <div className="bg-danger/10 border border-danger/30 rounded-2xl p-4 flex items-center gap-3">
                <AlertTriangle className="text-danger" size={20} />
                <p className="text-sm">
                  <span className="font-semibold">{stats.pending_reports} новых жалоб</span> ожидают обработки.
                </p>
                <button
                  onClick={() => setTab("reports")}
                  className="ml-auto px-3 py-1.5 bg-danger/20 text-danger text-sm rounded-lg hover:bg-danger/30"
                >
                  Открыть →
                </button>
              </div>
            )}
          </div>
        )}

        {tab === "users" && <UsersTable />}
        {tab === "reports" && <ReportsTable />}
        {tab === "moderation" && <ModerationLogsTable />}
        {tab === "sections" && <SectionsTable />}
      </div>
    </div>
  );
}
