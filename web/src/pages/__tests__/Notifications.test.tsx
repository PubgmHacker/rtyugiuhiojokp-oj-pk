/**
 * Центр уведомлений — лента событий без собственного экрана.
 *
 * Три обещания, за которыми следит этот файл:
 * 1. Тексты итогов жалоб дословно зеркалят пуши report_notify.py — пуш и
 *    карточка описывают одно и то же событие, расходиться им нельзя.
 * 2. Незнакомый kind (событие из более новой версии API) молча прячется:
 *    старый клиент показывает «Пока тихо», а не карточку с «undefined».
 * 3. Открытие страницы гасит точку колокольчика сразу и зовёт POST /read —
 *    но только когда непрочитанное есть: пустой визит сервер не дёргает.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Notifications from "../Notifications";
import * as api from "../../lib/api";
import { useStore } from "../../lib/store";

function событие(
  id: string,
  kind: string,
  payload: Record<string, string>,
  read_at: string | null = null
): api.NotificationItem {
  return { id, kind, payload, created_at: "2026-08-22T12:00:00+00:00", read_at };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useStore.setState({ unreadNotifications: 0 });
});

describe("Центр уведомлений", () => {
  it("итоги жалоб зеркалят тексты пушей, точка гаснет сразу", async () => {
    useStore.setState({ unreadNotifications: 2 });
    vi.spyOn(api, "getNotifications").mockResolvedValue({
      items: [
        событие("n1", "report_outcome", { outcome: "hidden" }),
        событие("n2", "report_outcome", { outcome: "banned" }, "2026-08-21T10:00:00+00:00"),
        событие("n3", "report_outcome", { outcome: "resolved" }, "2026-08-20T10:00:00+00:00"),
        событие("n4", "report_outcome", { outcome: "dismissed" }, "2026-08-19T10:00:00+00:00"),
        событие("n5", "verification_approved", {}),
      ],
      unread: 2,
    });
    const прочитать = vi
      .spyOn(api, "markNotificationsRead")
      .mockResolvedValue({ read: 2 });

    render(
      <MemoryRouter>
        <Notifications />
      </MemoryRouter>
    );

    // Каждый исход — своим текстом, слово в слово как в пуше
    expect(await screen.findByText("Жалоба сработала")).toBeInTheDocument();
    expect(
      screen.getByText("Анкета скрыта из поиска — её проверит модератор.")
    ).toBeInTheDocument();
    expect(screen.getByText("Жалоба подтверждена")).toBeInTheDocument();
    expect(
      screen.getByText("Аккаунт заблокирован. Больше он вам не встретится.")
    ).toBeInTheDocument();
    // resolved и dismissed делят заголовок, но не текст
    expect(screen.getAllByText("Жалоба рассмотрена")).toHaveLength(2);
    expect(
      screen.getByText("Модератор проверил анкету и принял меры.")
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Модератор не нашёл нарушения правил. Мешающего человека можно " +
          "заблокировать в его анкете."
      )
    ).toBeInTheDocument();
    expect(screen.getByText("Профиль подтверждён")).toBeInTheDocument();

    // Непрочитанные (read_at == null) помечены точкой, прочитанные — нет
    expect(screen.getAllByLabelText("Новое")).toHaveLength(2);

    // Колокольчик гаснет локально сразу, сервер — фоном одним запросом
    expect(useStore.getState().unreadNotifications).toBe(0);
    await waitFor(() => expect(прочитать).toHaveBeenCalledTimes(1));
  });

  it("незнакомый вид события молча прячется, пустой визит не дёргает /read", async () => {
    vi.spyOn(api, "getNotifications").mockResolvedValue({
      items: [событие("n1", "gift_received_2027", { gift: "🎁" })],
      unread: 0,
    });
    const прочитать = vi
      .spyOn(api, "markNotificationsRead")
      .mockResolvedValue({ read: 0 });

    render(
      <MemoryRouter>
        <Notifications />
      </MemoryRouter>
    );

    // Лента из одних незнакомых событий — это «Пока тихо», не пустые карточки
    expect(await screen.findByText("Пока тихо")).toBeInTheDocument();
    expect(прочитать).not.toHaveBeenCalled();
  });

  it("сбой сети показывает LoadError, «Повторить» перезапрашивает", async () => {
    vi.spyOn(api, "getNotifications")
      .mockRejectedValueOnce(new Error("нет сети"))
      .mockResolvedValueOnce({
        items: [событие("n1", "verification_approved", {})],
        unread: 0,
      });
    vi.spyOn(api, "markNotificationsRead").mockResolvedValue({ read: 0 });

    render(
      <MemoryRouter>
        <Notifications />
      </MemoryRouter>
    );

    expect(await screen.findByText("Не удалось загрузить")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByText("Профиль подтверждён")).toBeInTheDocument();
  });
});
