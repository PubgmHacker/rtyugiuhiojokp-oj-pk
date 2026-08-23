/**
 * Вход в полный профиль собеседника из чата: тап по аватару или имени в
 * шапке открывает ProfileSheet. Раньше из чата анкету было не открыть
 * вообще (аудит, блок «Продукт») — а решение «встречаться ли» принимают
 * ровно здесь, уже переписываясь.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, cleanup, fireEvent } from "@testing-library/react";
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

function партнёрша(): api.UserProfile {
  return {
    id: "partner-anya",
    display_name: "Аня",
    age: 24,
    bio: "Люблю горы и старое кино",
    gender: "female",
    city: "Москва",
    photos: ["https://x/1.jpg"],
    interests: ["кино", "горы"],
    looking_for: "",
    is_incognito: false,
  } as api.UserProfile;
}

async function открытьЧат() {
  useStore.setState({ token: "test-token" });
  vi.spyOn(api, "getMessages").mockResolvedValue([]);
  vi.spyOn(api, "getMatches").mockResolvedValue([
    { id: "match-a", partner: партнёрша() } as unknown as api.MatchResponse,
  ]);

  const router = createMemoryRouter(
    [{ path: "/chat/:matchId", element: <Chat /> }],
    { initialEntries: ["/chat/match-a"] }
  );
  render(<RouterProvider router={router} />);
  await waitFor(() => expect(api.getMessages).toHaveBeenCalled());
  await screen.findByText("Аня");
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useStore.setState({ token: "test-token" });
});

describe("Чат → профиль собеседника", () => {
  it("тап по шапке открывает полный профиль и закрывается обратно в чат", async () => {
    await открытьЧат();

    // До тапа профиля нет, био в чате не светится
    expect(screen.queryByText(/Люблю горы/)).toBeNull();

    fireEvent.click(screen.getByLabelText("Профиль Аня"));

    expect(await screen.findByRole("dialog", { name: "Профиль Аня" })).toBeInTheDocument();
    expect(screen.getByText(/Люблю горы и старое кино/)).toBeInTheDocument();
    expect(screen.getByText("Москва")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Закрыть профиль"));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Профиль Аня" })).toBeNull()
    );
    // Чат жив — поле ввода на месте
    expect(screen.getByPlaceholderText(/Сообщение|сообщение/)).toBeInTheDocument();
  });
});
