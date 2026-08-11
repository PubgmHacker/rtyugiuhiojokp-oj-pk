/**
 * Экран чата переиспользуется между разными matchId без размонтирования
 * (переход по маршруту /chat/:matchId → /chat/:otherId). Если ответ на
 * getMessages() для СТАРОГО matchId придёт позже, чем эффект перезапустится
 * на НОВОМ matchId, применять его нельзя — иначе он молча подменит уже
 * открытую переписку сообщениями чужого мэтча.
 * См. web/src/pages/Chat.tsx, эффект "Загрузка истории и сокет".
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, act, waitFor, cleanup } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import Chat from "../Chat";
import * as api from "../../lib/api";
import { useStore } from "../../lib/store";

// Сокет-часть эффекта уже покрыта существующим поведением (offStatus/offMessage/
// ws.close() и т.д.) и не является предметом этого теста — подменяем класс,
// чтобы тест не зависел от реального WebSocket в jsdom.
vi.mock("../../lib/websocket", () => {
  class FakeChatWebSocket {
    onStatusChange() {
      return () => {};
    }
    onMessage() {
      return () => {};
    }
    onOpen() {
      return () => {};
    }
    connect() {}
    close() {}
    sendRaw() {}
    send() {
      return true;
    }
  }
  return { ChatWebSocket: FakeChatWebSocket };
});

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

function partner(name: string): api.UserProfile {
  return {
    id: `partner-${name}`,
    display_name: name,
    bio: "",
    gender: "",
    city: "",
    photos: [],
    interests: [],
    looking_for: "",
    is_incognito: false,
  } as api.UserProfile;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useStore.setState({ token: "test-token" });
});

describe("Chat — гонка загрузки истории при смене matchId", () => {
  it("не применяет устаревший ответ getMessages/getMatches к новому matchId", async () => {
    useStore.setState({ token: "test-token" });

    const matchA = deferred<api.ChatMessage[]>();
    const matchB = deferred<api.ChatMessage[]>();

    vi.spyOn(api, "getMessages").mockImplementation((matchId: string) =>
      matchId === "match-a" ? (matchA.promise as any) : (matchB.promise as any)
    );
    vi.spyOn(api, "getMatches").mockResolvedValue([
      { id: "match-a", partner: partner("Аня") } as unknown as api.MatchResponse,
      { id: "match-b", partner: partner("Боря") } as unknown as api.MatchResponse,
    ]);

    // Один и тот же роутер на весь тест: навигация должна перерендерить Chat
    // с новым matchId без размонтирования — это и есть условие гонки.
    const router = createMemoryRouter(
      [{ path: "/chat/:matchId", element: <Chat /> }],
      { initialEntries: ["/chat/match-a"] }
    );

    render(<RouterProvider router={router} />);

    await waitFor(() => expect(api.getMessages).toHaveBeenCalledWith("match-a"));

    // Пользователь уходит в другой чат раньше, чем ответ на match-a пришёл.
    await act(async () => {
      await router.navigate("/chat/match-b");
    });

    await waitFor(() => expect(api.getMessages).toHaveBeenCalledWith("match-b"));

    // Новый (match-b) запрос отвечает первым.
    await act(async () => {
      matchB.resolve([
        {
          id: "msg-b1",
          match_id: "match-b",
          sender_id: "partner-Боря",
          text: "привет из B",
          created_at: new Date().toISOString(),
        },
      ]);
      await matchB.promise;
    });

    await waitFor(() => expect(screen.getByText("привет из B")).toBeInTheDocument());

    // Старый (match-a) запрос отвечает позже — его результат должен быть отброшен,
    // а не подменить уже показанную переписку с "Борей".
    await act(async () => {
      matchA.resolve([
        {
          id: "msg-a1",
          match_id: "match-a",
          sender_id: "partner-Аня",
          text: "привет из A",
          created_at: new Date().toISOString(),
        },
      ]);
      await matchA.promise;
    });

    expect(screen.queryByText("привет из A")).not.toBeInTheDocument();
    expect(screen.getByText("привет из B")).toBeInTheDocument();
  });
});

describe("Chat — сбой загрузки истории", () => {
  it("отличает «не загрузилось» от «переписки ещё нет»", async () => {
    useStore.setState({ token: "test-token" });

    // Сеть недоступна: раньше это молча показывало приглашение написать
    // первым, и человек думал, что собеседник ничего не писал
    vi.spyOn(api, "getMessages").mockRejectedValue(new Error("сеть недоступна"));
    // В список мэтчей при этом всё равно ничего не приходит: UI без него
    // не собирает себя, а ждёт. Поэтому и не зовём.
    vi.spyOn(api, "getMatches").mockRejectedValue(new Error("сеть недоступна"));

    const router = createMemoryRouter(
      [{ path: "/chat/:matchId", element: <Chat /> }],
      { initialEntries: ["/chat/match-a"] }
    );

    render(<RouterProvider router={router} />);

    await waitFor(() =>
      expect(screen.getByText("Не удалось загрузить переписку")).toBeInTheDocument()
    );
    // Приглашение написать первым тут неуместно — оно врёт про состояние
    expect(screen.queryByText("Вы понравились друг другу")).not.toBeInTheDocument();
  });
});
