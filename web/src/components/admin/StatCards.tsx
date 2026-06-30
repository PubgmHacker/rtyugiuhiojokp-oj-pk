import { Users, Heart, AlertTriangle, Crown, UserCheck, Ban } from "lucide-react";
import type { AdminStats } from "../../lib/admin";

interface Props {
  stats: AdminStats | null;
  loading: boolean;
}

export default function StatCards({ stats, loading }: Props) {
  if (loading || !stats) {
    return (
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[...Array(8)].map((_, i) => (
          <div key={i} className="h-28 bg-surface rounded-2xl animate-pulse" />
        ))}
      </div>
    );
  }

  const cards = [
    { label: "Всего пользователей", value: stats.total_users, icon: Users, color: "text-accent", sub: `+${stats.new_users_week} за неделю` },
    { label: "Активны сегодня", value: stats.active_today, icon: UserCheck, color: "text-success", sub: `${Math.round((stats.active_today / Math.max(stats.total_users, 1)) * 100)}% от базы` },
    { label: "Всего мэтчей", value: stats.total_matches, icon: Heart, color: "text-warn", sub: `${stats.total_likes} лайков всего` },
    { label: "Жалобы (новые)", value: stats.pending_reports, icon: AlertTriangle, color: "text-danger", sub: `${stats.total_reports} всего` },
    { label: "Premium", value: stats.premium_users, icon: Crown, color: "text-warn", sub: `${Math.round((stats.premium_users / Math.max(stats.total_users, 1)) * 100)}% конверсия` },
    { label: "Заблокировано", value: stats.banned_users, icon: Ban, color: "text-danger", sub: `${Math.round((stats.banned_users / Math.max(stats.total_users, 1)) * 100)}% базы` },
    { label: "Новые (месяц)", value: stats.new_users_month, icon: Users, color: "text-accent", sub: "за 30 дней" },
    { label: "Новые (неделя)", value: stats.new_users_week, icon: Users, color: "text-accent", sub: "за 7 дней" },
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {cards.map((card, i) => (
        <div key={i} className="bg-surface rounded-2xl p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-text-muted">{card.label}</span>
            <card.icon size={18} className={card.color} />
          </div>
          <p className="text-2xl font-bold mb-1">{card.value.toLocaleString()}</p>
          <p className="text-xs text-text-muted">{card.sub}</p>
        </div>
      ))}
    </div>
  );
}
