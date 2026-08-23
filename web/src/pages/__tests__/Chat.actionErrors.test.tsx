/**
 * Жалоба, блокировка и размэтч из чата раньше падали молча: catch давал
 * одну вибрацию — человек был уверен, что жалоба ушла, хотя сервер её не
 * получил (аудит, блок «Доверие»). Теперь сбой показывает плашку с текстом,
 * а успех жалобы не маскируется сбоем вспомогательного размэтча.
 * См. sendReport / handleBlock / handleUnmatch в web/src/pages/Chat.tsx.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import {
  render,
  screen,
  waitFor,
  cleanup,
  fireEvent,
} from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import Chat from "../Chat";
import * as api from "../../lib/api";
import { useStore } from "../../lib/store";

// Сокет не предмет теста — двойник, как в Chat.race.test.tsx (там же есть
// тест, сверяющий набор методов двойника с вызовами в Chat.tsx).
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
    onFatalClose() {
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

/** Ошибка в форме, которую даёт axios: detail сервера внутри response.data. */
function сбой(status: number, detail?: string) {
  const e: any = new Error(`HTTP ${status}`);
  e.response = { status, data: detail ? { detail } : {} };
  return e;
}

async function открытьЧат() {
  useStore.setState({ token: "test-token" });
  vi.spyOn(api, "getMessages").mockResolvedValue([]);
  vi.spyOn(api, "getMatches").mockResolvedValue([
    { id: "match-a", partner: partner("Аня") } as unknown as api.MatchResponse,
  ]);

  const router = createMemoryRouter(
    [
      { path: "/chat/:matchId", element: <Chat /> },
      { path: "/matches", element: <div>Список мэтчей</div> },
    ],
    { initialEntries: ["/chat/match-a"] }
  );
  render(<RouterProvider router={router} />);
  await waitFor(() => expect(api.getMessages).toHaveBeenCalled());
  // Меню собирается, когда мэтч загружен — ждём имя партнёра в шапке
  await screen.findByText("Аня");
  return router;
}

async function пожаловаться() {
  fireEvent.click(screen.getByLabelText("Действия"));
  fireEvent.click(await screen.findByText("Пожаловаться"));
  fireEvent.click(await screen.findByText("Спам или реклама"));
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useStore.setState({ token: "test-token" });
});

describe("Chat — сбои жалобы/блокировки/размэтча видимы", () => {
  it("жалоба не ушла: плашка с текстом, мэтч не тронут, остаёмся в чате", async () => {
    vi.spyOn(api, "reportUser").mockRejectedValue(сбой(500));
    const unmatchSpy = vi.spyOn(api, "unmatch").mockResolvedValue(undefined as any);

    const router = await открытьЧат();
    await пожаловаться();

    await screen.findByText(/Жалоба не отправлена/);
    expect(unmatchSpy).not.toHaveBeenCalled();
    expect(router.state.location.pathname).toBe("/chat/match-a");

    // Плашка закрывается тапом — иначе висела бы до конца сессии
    fireEvent.click(screen.getByText(/Жалоба не отправлена/));
    expect(screen.queryByText(/Жалоба не отправлена/)).toBeNull();
  });

  it("содержательный отказ сервера показывается его же словами", async () => {
    vi.spyOn(api, "reportUser").mockRejectedValue(
      сбой(429, "Слишком много жалоб — попробуйте позже")
    );
    vi.spyOn(api, "unmatch").mockResolvedValue(undefined as any);

    await открытьЧат();
    await пожаловаться();

    await screen.findByText(/Слишком много жалоб/);
  });

  it("жалоба дошла, а размэтч упал: уходим к мэтчам без пугающей плашки", async () => {
    vi.spyOn(api, "reportUser").mockResolvedValue(undefined as any);
    vi.spyOn(api, "unmatch").mockRejectedValue(сбой(500));

    const router = await открытьЧат();
    await пожаловаться();

    // Жалоба у модератора — «не отправлена» была бы ложью
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/matches")
    );
    expect(screen.queryByText(/Жалоба не отправлена/)).toBeNull();
  });

  it("блокировка упала: плашка, остаёмся в чате", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(api, "blockUser").mockRejectedValue(сбой(500));

    const router = await открытьЧат();
    fireEvent.click(screen.getByLabelText("Действия"));
    fireEvent.click(await screen.findByText("Заблокировать"));

    await screen.findByText(/Не удалось заблокировать/);
    expect(router.state.location.pathname).toBe("/chat/match-a");
  });

  it("размэтч упал: плашка, остаёмся в чате", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(api, "unmatch").mockRejectedValue(сбой(500));

    const router = await открытьЧат();
    fireEvent.click(screen.getByLabelText("Действия"));
    fireEvent.click(await screen.findByText("Разорвать мэтч"));

    await screen.findByText(/Не удалось разорвать мэтч/);
    expect(router.state.location.pathname).toBe("/chat/match-a");
  });
});
