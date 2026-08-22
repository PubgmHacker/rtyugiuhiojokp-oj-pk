/**
 * Карточка пользователя в админке — досье с действиями.
 *
 * Что закрепляется:
 *
 * 1. Бан из карточки уходит на сервер СО СРОКОМ И ПРИЧИНОЙ — ради этого
 *    карточка и строилась (кнопка в строке таблицы умеет только вечный бан).
 *    Сломается проводка duration_hours → админ будет думать, что выдал сутки,
 *    а человек получит навсегда.
 * 2. После действия досье перечитывается с сервера: banned_until, амнистию
 *    страйков и запись в журнале считает бэкенд, локальная правка разошлась
 *    бы с ним. Таблице уходит только патч строки (is_banned/is_verified).
 * 3. Админов и владельца из карточки забанить нельзя — как и в таблице.
 * 4. Страйки подсвечиваются по лимиту автоматики: «2 из 2» — красный, дальше
 *    автобан; модератор видит, на каком шаге лестницы человек стоит.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import UserCard from "../UserCard";
import type { AdminUserCard } from "../../../lib/admin";

vi.mock("../../../lib/admin", () => ({
  getAdminUserCard: vi.fn(),
  banUser: vi.fn().mockResolvedValue(undefined),
  unbanUser: vi.fn().mockResolvedValue(undefined),
  setUserVerified: vi.fn().mockResolvedValue(undefined),
}));

import { getAdminUserCard, banUser, unbanUser } from "../../../lib/admin";

/** Обычный смертный без нарушений; тесты переопределяют нужные поля. */
function досье(правки: Partial<AdminUserCard> = {}): AdminUserCard {
  return {
    id: "u1",
    telegram_id: 100,
    role: "user",
    locale: "ru",
    is_banned: false,
    banned_until: null,
    is_verified: false,
    created_at: "2026-01-01T00:00:00",
    last_seen_at: null,
    has_apple: false,
    has_email: false,
    display_name: "Ума",
    gender: "female",
    age: 26,
    city: "Ташкент",
    bio: "",
    photos: [],
    interests: [],
    is_incognito: false,
    is_paused: false,
    plan: "free",
    plan_expires_at: null,
    matches_count: 0,
    likes_sent: 0,
    likes_received: 0,
    reels_count: 0,
    stories_count: 0,
    strikes: {
      ad: { count: 0, limit: 3, window_days: 30 },
      heavy: { count: 0, limit: 2, window_days: 30 },
      text: { count: 0, limit: 5, window_days: 7 },
      content: { count: 0, limit: 3, window_days: 90 },
    },
    prior_bans: 0,
    reports_against: 0,
    reports_pending: 0,
    reports_by: 0,
    last_verification: null,
    recent_moderation: [],
    ...правки,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("UserCard: бан со сроком", () => {
  it("отправляет выбранный срок и причину, патчит строку и перечитывает досье", async () => {
    vi.mocked(getAdminUserCard).mockResolvedValue(досье());
    const onChanged = vi.fn();
    render(<UserCard userId="u1" onClose={() => {}} onChanged={onChanged} />);
    await screen.findByText("Ума");

    // Срок «7 суток» + причина
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "168" } });
    fireEvent.change(screen.getByPlaceholderText(/Причина/), {
      target: { value: "реклама в анкете" },
    });
    fireEvent.click(screen.getByText("Забанить"));

    await waitFor(() =>
      expect(banUser).toHaveBeenCalledWith("u1", "реклама в анкете", 168)
    );
    expect(onChanged).toHaveBeenCalledWith({ is_banned: true });
    // Досье после действия перечитано: сервер знает banned_until и амнистию
    expect(getAdminUserCard).toHaveBeenCalledTimes(2);
  });

  it("«Навсегда» уходит как null — прежняя семантика вечного бана", async () => {
    vi.mocked(getAdminUserCard).mockResolvedValue(досье());
    render(<UserCard userId="u1" onClose={() => {}} onChanged={() => {}} />);
    await screen.findByText("Ума");

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "forever" } });
    fireEvent.click(screen.getByText("Забанить"));

    await waitFor(() => expect(banUser).toHaveBeenCalledWith("u1", "", null));
  });

  it("админа забанить нельзя — вместо формы бана пояснение", async () => {
    vi.mocked(getAdminUserCard).mockResolvedValue(досье({ role: "admin" }));
    render(<UserCard userId="u1" onClose={() => {}} onChanged={() => {}} />);
    await screen.findByText("Ума");

    expect(screen.queryByText("Забанить")).toBeNull();
    expect(screen.getByText(/банить нельзя/)).toBeTruthy();
  });

  it("у забаненного — разбан, который патчит строку", async () => {
    vi.mocked(getAdminUserCard).mockResolvedValue(
      досье({ is_banned: true, banned_until: null })
    );
    const onChanged = vi.fn();
    render(<UserCard userId="u1" onClose={() => {}} onChanged={onChanged} />);
    await screen.findByText("Ума");
    expect(screen.getByText("забанен навсегда")).toBeTruthy();

    fireEvent.click(screen.getByText(/Разбанить/));
    await waitFor(() => expect(unbanUser).toHaveBeenCalledWith("u1"));
    expect(onChanged).toHaveBeenCalledWith({ is_banned: false });
  });
});

describe("UserCard: чтение досье", () => {
  it("страйк на лимите подсвечен как красный — дальше автобан", async () => {
    vi.mocked(getAdminUserCard).mockResolvedValue(
      досье({
        strikes: {
          ad: { count: 2, limit: 3, window_days: 30 },
          heavy: { count: 2, limit: 2, window_days: 30 },
          text: { count: 0, limit: 5, window_days: 7 },
          content: { count: 0, limit: 3, window_days: 90 },
        },
      })
    );
    render(<UserCard userId="u1" onClose={() => {}} onChanged={() => {}} />);
    await screen.findByText("Ума");

    // heavy: 2 из 2 — на лимите, danger; ad: 2 из 3 — предупреждение, warn
    expect(screen.getByText("2 из 2").className).toContain("text-danger");
    expect(screen.getByText("2 из 3").className).toContain("text-warn");
  });

  it("ошибка загрузки — не пустой экран, а «Повторить»", async () => {
    vi.mocked(getAdminUserCard).mockRejectedValueOnce(new Error("сеть"));
    render(<UserCard userId="u1" onClose={() => {}} onChanged={() => {}} />);

    const повтор = await screen.findByText("Повторить");
    vi.mocked(getAdminUserCard).mockResolvedValue(досье());
    fireEvent.click(повтор);
    await screen.findByText("Ума");
  });
});
