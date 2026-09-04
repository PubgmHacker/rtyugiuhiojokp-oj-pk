/**
 * Снимок из галереи в переписке. Кнопка стоит слева от поля — как в ВК и
 * Telegram — и грузит файл в отдельную дверь `/upload/chat-photo`: дверь
 * анкеты требует хорошо видимое лицо владельца и завернула бы кота, чек и
 * скриншот. Проверяем три вещи, на которых это ломается в бою: снимок
 * уходит в вебсокет ссылкой, тяжёлый файл отбивается ДО загрузки (иначе
 * отказ приезжает через полминуты мобильного интернета), а отказ сервера
 * показывается его же словами.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, cleanup, fireEvent } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import Chat from "../Chat";
import * as api from "../../lib/api";
import { useStore } from "../../lib/store";

const { отправлено } = vi.hoisted(() => ({ отправлено: vi.fn(() => true) }));

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
    send(...аргументы: unknown[]) {
      return отправлено(...(аргументы as []));
    }
  }
  return { ChatWebSocket: FakeChatWebSocket };
});

function партнёрша(): api.UserProfile {
  return {
    id: "partner-anya",
    display_name: "Аня",
    age: 24,
    bio: "",
    gender: "female",
    city: "Москва",
    photos: [],
    interests: [],
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

  const router = createMemoryRouter([{ path: "/chat/:matchId", element: <Chat /> }], {
    initialEntries: ["/chat/match-a"],
  });
  const { container } = render(<RouterProvider router={router} />);
  await waitFor(() => expect(api.getMessages).toHaveBeenCalled());
  await screen.findByText("Аня");
  return container;
}

/** Файл нужного веса: настоящих десяти мегабайт в тесте не держим. */
function снимок(имя: string, тип: string, байт: number): File {
  const f = new File(["x"], имя, { type: тип });
  Object.defineProperty(f, "size", { value: байт });
  return f;
}

function выбрать(container: HTMLElement, file: File) {
  const вход = container.querySelector('input[type="file"]') as HTMLInputElement;
  expect(вход).toBeTruthy();
  fireEvent.change(вход, { target: { files: [file] } });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  отправлено.mockClear();
  отправлено.mockReturnValue(true);
  useStore.setState({ token: "test-token" });
});

describe("Чат → отправка фото", () => {
  it("снимок уходит ссылкой в вебсокет, а не текстом", async () => {
    const upload = vi
      .spyOn(api, "uploadChatPhoto")
      .mockResolvedValue({ url: "https://r2.example/chat-media/u-me/photo-1.jpg", key: "k" });
    const container = await открытьЧат();

    expect(screen.getByRole("button", { name: "Отправить фото" })).toBeInTheDocument();
    выбрать(container, снимок("cat.jpg", "image/jpeg", 240 * 1024));

    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(отправлено).toHaveBeenCalledWith(
        "",
        "https://r2.example/chat-media/u-me/photo-1.jpg",
        undefined,
        undefined
      )
    );
  });

  it("тяжёлый файл отбивается до загрузки", async () => {
    const upload = vi.spyOn(api, "uploadChatPhoto");
    const container = await открытьЧат();

    выбрать(container, снимок("huge.jpg", "image/jpeg", 11 * 1024 * 1024));

    expect(await screen.findByText(/Снимок больше 10 МБ/)).toBeInTheDocument();
    expect(upload).not.toHaveBeenCalled();
    expect(отправлено).not.toHaveBeenCalled();
  });

  it("отказ сервера показывается его же словами", async () => {
    vi.spyOn(api, "uploadChatPhoto").mockRejectedValue({
      response: { status: 422, data: { detail: "Снимок нарушает правила сервиса" } },
    });
    const container = await открытьЧат();

    выбрать(container, снимок("bad.jpg", "image/jpeg", 100 * 1024));

    expect(await screen.findByText(/Снимок нарушает правила сервиса/)).toBeInTheDocument();
    expect(отправлено).not.toHaveBeenCalled();
  });
});
