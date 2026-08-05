import api from "./api";

// ── Admin Types ────────────────────────────────────────────────

export interface AdminStats {
  total_users: number;
  active_today: number;
  total_matches: number;
  total_likes: number;
  total_reports: number;
  pending_reports: number;
  premium_users: number;
  banned_users: number;
  new_users_week: number;
  new_users_month: number;
  registrations_chart: { date: string; count: number }[];
}

export interface AdminUser {
  id: string;
  telegram_id: number | null;
  display_name: string;
  gender: string;
  age: number | null;
  city: string;
  role: string;
  is_banned: boolean;
  is_verified: boolean;
  created_at: string | null;
}

export interface AdminReport {
  id: string;
  reporter_id: string;
  reporter_name: string;
  reported_id: string;
  reported_name: string;
  reason: string;
  description: string;
  status: string;
  created_at: string | null;
}

export interface AdminModerationLog {
  id: string;
  user_id: string;
  user_name: string;
  content_type: string;
  content_preview: string;
  result: string;
  action: string;
  reason: string;
  created_at: string | null;
}

// ── Admin API ──────────────────────────────────────────────────

export async function getAdminStats(): Promise<AdminStats> {
  const { data } = await api.get("/admin/stats");
  return data;
}

export async function getAdminUsers(
  page = 1,
  limit = 50,
  search = "",
  bannedOnly = false
): Promise<AdminUser[]> {
  const { data } = await api.get("/admin/users", {
    params: { page, limit, search, banned_only: bannedOnly },
  });
  return data;
}

export async function banUser(userId: string, reason = ""): Promise<void> {
  await api.post("/admin/users/ban", { user_id: userId, reason });
}

export async function unbanUser(userId: string): Promise<void> {
  await api.post("/admin/users/unban", { user_id: userId });
}

export async function getAdminReports(
  status = "pending",
  page = 1,
  limit = 50
): Promise<AdminReport[]> {
  const { data } = await api.get("/admin/reports", {
    params: { status, page, limit },
  });
  return data;
}

export async function resolveReport(
  reportId: string,
  action: "dismiss" | "resolve" | "ban_reported",
  note = ""
): Promise<void> {
  await api.post("/admin/reports/action", { report_id: reportId, action, note });
}

export async function getModerationLogs(
  resultFilter = "all",
  page = 1,
  limit = 50
): Promise<AdminModerationLog[]> {
  const { data } = await api.get("/admin/moderation-logs", {
    params: { result_filter: resultFilter, page, limit },
  });
  return data;
}

/* ── Сводка по разделам ─────────────────────────────────────── */

export interface SectionStat {
  section: string;
  users: number;
  opens: number;
  /** Какая доля людей вообще заходила в раздел. */
  reach_percent: number;
}

export interface SectionStats {
  days: number;
  total_users: number;
  sections: SectionStat[];
}

/**
 * По этой сводке решают, какие разделы оставить. Живёт не в /admin, а в
 * /sections: запись открытия делает обычный пользователь, и держать половину
 * ручки в админском роутере значило бы разнести одну фичу по двум местам.
 */
export async function getSectionStats(days = 30): Promise<SectionStats> {
  const { data } = await api.get("/sections/stats", { params: { days } });
  return data;
}
