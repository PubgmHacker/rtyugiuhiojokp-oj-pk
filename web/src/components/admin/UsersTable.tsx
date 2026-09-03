import { useState, useEffect, useCallback } from "react";
import { Search, Shield, ShieldOff, BadgeCheck } from "lucide-react";
import {
  getAdminUsers,
  banUser,
  unbanUser,
  setUserVerified,
  type AdminUser,
} from "../../lib/admin";
import UserCard from "./UserCard";

export default function UsersTable() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [bannedOnly, setBannedOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  // Клик по строке открывает досье; кнопки в строке — для бесспорных случаев
  const [openUserId, setOpenUserId] = useState<string | null>(null);
  // Сбой — не «Нет пользователей»: пустая таблица при упавшей сети — ложь
  const [сбой, setСбой] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setСбой(false);
    try {
      const data = await getAdminUsers(page, 50, search, bannedOnly);
      setUsers(data);
    } catch (e) {
      console.error(e);
      setСбой(true);
    } finally {
      setLoading(false);
    }
  }, [page, search, bannedOnly]);

  useEffect(() => {
    load();
  }, [load]);

  const handleBan = async (userId: string) => {
    setActionLoading(userId);
    try {
      await banUser(userId);
      setUsers(users.map((u) => (u.id === userId ? { ...u, is_banned: true } : u)));
    } catch (e) {
      console.error(e);
    }
    setActionLoading(null);
  };

  const handleUnban = async (userId: string) => {
    setActionLoading(userId);
    try {
      await unbanUser(userId);
      setUsers(users.map((u) => (u.id === userId ? { ...u, is_banned: false } : u)));
    } catch (e) {
      console.error(e);
    }
    setActionLoading(null);
  };

  // Ручная галочка: снять с подменившего фото, выдать тому, кого AI не узнаёт
  const handleVerified = async (userId: string, verified: boolean) => {
    setActionLoading(userId);
    try {
      await setUserVerified(userId, verified);
      setUsers(users.map((u) => (u.id === userId ? { ...u, is_verified: verified } : u)));
    } catch (e) {
      console.error(e);
    }
    setActionLoading(null);
  };

  return (
    <div className="bg-surface rounded-2xl overflow-hidden">
      {/* Header + search */}
      <div className="flex flex-col sm:flex-row gap-3 p-4 border-b border-white/5">
        <div className="relative flex-1">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
          <input
            type="text"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            placeholder="Поиск по имени или Telegram ID..."
            className="w-full pl-9 pr-4 py-2 bg-bg rounded-xl text-sm outline-none focus:ring-1 focus:ring-accent"
          />
        </div>
        <button
          onClick={() => { setBannedOnly(!bannedOnly); setPage(1); }}
          className={`px-4 py-2 rounded-xl text-sm font-medium transition ${
            bannedOnly
              ? "bg-danger/20 text-danger"
              : "bg-bg text-text-muted hover:text-text"
          }`}
        >
          {bannedOnly ? "Только забаненные" : "Все пользователи"}
        </button>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-text-muted text-xs uppercase tracking-wider">
              <th className="px-4 py-3">Пользователь</th>
              <th className="px-4 py-3 hidden sm:table-cell">Пол</th>
              <th className="px-4 py-3 hidden md:table-cell">Город</th>
              <th className="px-4 py-3">Роль</th>
              <th className="px-4 py-3">Статус</th>
              <th className="px-4 py-3 hidden lg:table-cell">Дата</th>
              <th className="px-4 py-3 text-right">Действия</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              [...Array(10)].map((_, i) => (
                <tr key={i} className="border-t border-white/5">
                  {[...Array(7)].map((__, j) => (
                    <td key={j} className="px-4 py-3">
                      <div className="h-4 bg-bg rounded animate-pulse w-3/4" />
                    </td>
                  ))}
                </tr>
              ))
            ) : сбой ? (
              <tr>
                <td colSpan={7} className="px-4 py-12 text-center text-text-muted">
                  <p className="mb-3">Не удалось загрузить</p>
                  <button
                    onClick={load}
                    className="px-4 py-2 bg-bg rounded-xl text-sm font-medium hover:text-text transition"
                  >
                    Повторить
                  </button>
                </td>
              </tr>
            ) : users.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-12 text-center text-text-muted">
                  Нет пользователей
                </td>
              </tr>
            ) : (
              users.map((u) => (
                <tr
                  key={u.id}
                  onClick={() => setOpenUserId(u.id)}
                  className="border-t border-white/5 hover:bg-white/[0.02] transition cursor-pointer"
                >
                  <td className="px-4 py-3">
                    <div>
                      <p className="font-medium truncate max-w-[150px]">{u.display_name || "—"}</p>
                      <p className="text-xs text-text-muted">
                        TG:{u.telegram_id ?? "—"} · {u.id.slice(0, 8)}…
                      </p>
                    </div>
                  </td>
                  <td className="px-4 py-3 hidden sm:table-cell text-text-muted">
                    {u.gender === "male" ? "М" : u.gender === "female" ? "Ж" : "—"}
                  </td>
                  <td className="px-4 py-3 hidden md:table-cell text-text-muted">{u.city || "—"}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${
                      u.role === "owner"
                        ? "bg-warn/20 text-warn"
                        : u.role === "admin"
                        ? "bg-accent/20 text-accent"
                        : "bg-white/5 text-text-muted"
                    }`}>
                      {u.role}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${
                      u.is_banned
                        ? "bg-danger/20 text-danger"
                        : "bg-success/20 text-success"
                    }`}>
                      {u.is_banned ? "Забанен" : "Активен"}
                    </span>
                  </td>
                  <td className="px-4 py-3 hidden lg:table-cell text-text-muted text-xs">
                    {u.created_at ? new Date(u.created_at).toLocaleDateString("ru") : "—"}
                  </td>
                  {/* Кнопки не должны заодно открывать досье */}
                  <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center justify-end gap-1">
                      <button
                        onClick={() => handleVerified(u.id, !u.is_verified)}
                        disabled={actionLoading === u.id}
                        className={`p-1.5 rounded-lg transition disabled:opacity-40 ${
                          u.is_verified
                            ? "bg-info/10 text-info hover:bg-info/20"
                            : "bg-white/5 text-text-muted hover:text-text"
                        }`}
                        title={u.is_verified ? "Снять галочку" : "Выдать галочку вручную"}
                      >
                        <BadgeCheck size={16} />
                      </button>
                      {u.is_banned ? (
                        <button
                          onClick={() => handleUnban(u.id)}
                          disabled={actionLoading === u.id}
                          className="p-1.5 rounded-lg bg-success/10 text-success hover:bg-success/20 transition disabled:opacity-40"
                          title="Разбанить"
                        >
                          <ShieldOff size={16} />
                        </button>
                      ) : (
                        <button
                          onClick={() => handleBan(u.id)}
                          disabled={actionLoading === u.id || ["admin", "owner"].includes(u.role)}
                          className="p-1.5 rounded-lg bg-danger/10 text-danger hover:bg-danger/20 transition disabled:opacity-40"
                          title="Забанить"
                        >
                          <Shield size={16} />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
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
            disabled={users.length < 50}
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
          onChanged={(patch) =>
            setUsers((prev) =>
              prev.map((u) => (u.id === openUserId ? { ...u, ...patch } : u))
            )
          }
        />
      )}
    </div>
  );
}
