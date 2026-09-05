/**
 * Одна общая кнопка записи в чате — как в Telegram и ВК: тап меняет микрофон
 * на камеру, удержание пишет, короткий дубль улетает в корзину. Раньше здесь
 * стояли две кнопки (камера в поле ввода + микрофон рядом), и переключателя
 * режима не было вовсе.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, cleanup, fireEvent, act } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import Chat from "../Chat";
import * as api from "../../lib/api";
import { useStore } from "../../lib/store";

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

// В jsdom нет ни MediaRecorder, ни getUserMedia: подменяем только вход в
// запись, всё остальное в модуле (в том числе память режима) настоящее.
const { startRecording } = vi.hoisted(() => ({
  startRecording: vi.fn(async (kind: "voice" | "video_note") => ({
    kind,
    onLevel: () => () => {},
    attachPreview: () => {},
    stop: async () => ({ blob: new Blob(["x"]), duration: 2, waveform: "555", covers: [] }),
    cancel: () => {},
  })),
}));

vi.mock("../../lib/recorder", async (importOriginal) => {
  const настоящий = await importOriginal<typeof import("../../lib/recorder")>();
  return { ...настоящий, recordingSupported: () => true, startRecording };
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
  render(<RouterProvider router={router} />);
  await waitFor(() => expect(api.getMessages).toHaveBeenCalled());
  await screen.findByText("Аня");
}

const кнопка = () => screen.getByRole("button", { name: /держите, чтобы записать/ });
const курок = () => screen.getByRole("button", { name: /Идёт запись/ });

// В jsdom нет PointerEvent, а через fireEvent.pointerMove координаты до
// обработчика не доезжают — собираем событие сами на MouseEvent
function палец(
  тип: "pointerdown" | "pointermove" | "pointerup" | "pointercancel",
  el: Element,
  id: number,
  x: number,
  y: number
) {
  const ev = new MouseEvent(тип, { bubbles: true, cancelable: true, clientX: x, clientY: y });
  Object.defineProperty(ev, "pointerId", { value: id });
  fireEvent(el, ev);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  startRecording.mockClear();
  localStorage.clear();
  useStore.setState({ token: "test-token" });
});

describe("Чат → общая кнопка записи", () => {
  it("тап переключает микрофон на камеру и помнит выбор", async () => {
    await открытьЧат();

    // По умолчанию — голосовое, и второй кнопки записи в строке нет
    expect(kнопкаЛейбл()).toMatch(/^Голосовое/);
    expect(screen.queryByLabelText("Записать видеосообщение")).toBeNull();

    // Короткий тап: запись не началась, сменился режим
    палец("pointerdown", кнопка(), 1, 200, 700);
    палец("pointerup", кнопка(), 1, 200, 700);

    expect(kнопкаЛейбл()).toMatch(/^Кружок/);
    expect(startRecording).not.toHaveBeenCalled();
    expect(localStorage.getItem("sd_note_kind")).toBe("video_note");
    expect(await screen.findByText("Кружок · держите кнопку")).toBeInTheDocument();

    // Обратно
    палец("pointerdown", кнопка(), 2, 200, 700);
    палец("pointerup", кнопка(), 2, 200, 700);
    expect(kнопкаЛейбл()).toMatch(/^Голосовое/);
    expect(localStorage.getItem("sd_note_kind")).toBe("voice");
  });

  it("удержание пишет в текущем режиме, а слишком короткий дубль выбрасывает", async () => {
    localStorage.setItem("sd_note_kind", "video_note");
    await открытьЧат();

    палец("pointerdown", кнопка(), 3, 200, 700);
    // Держим дольше порога — поднимается камера, а не микрофон
    await act(async () => {
      await new Promise((r) => setTimeout(r, 340));
    });
    expect(startRecording).toHaveBeenCalledWith("video_note");
    expect(await screen.findByRole("group", { name: "Запись видеосообщения" })).toBeInTheDocument();
    // Под пальцем панель подсказывает, куда его вести, и корзины ещё нет
    expect(screen.getByText("← отмена · ↑ закрепить")).toBeInTheDocument();
    expect(screen.queryByLabelText("Отменить запись")).toBeNull();

    // Отпустили меньше чем через секунду — дубль не уходит
    палец("pointerup", курок(), 3, 200, 700);
    expect(await screen.findByText("Коротко — держите кнопку")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("group", { name: "Запись видеосообщения" })).toBeNull()
    );
  });

  it("подъём пальца закрепляет запись: появляются корзина и «Отправить»", async () => {
    await открытьЧат();

    палец("pointerdown", кнопка(), 4, 200, 700);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 340));
    });
    палец("pointermove", курок(), 4, 200, 640);

    expect(await screen.findByLabelText("Отменить запись")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Отправить запись" })).toBeInTheDocument();
    // Палец больше не держат — жест «отпустили» ничего не отправляет
    палец("pointerup", screen.getByRole("button", { name: "Отправить запись" }), 4, 200, 640);
    expect(screen.getByRole("button", { name: "Отправить запись" })).toBeInTheDocument();
  });
});

function kнопкаЛейбл(): string {
  return кнопка().getAttribute("aria-label") ?? "";
}

describe("Чат → строка ввода стоит вровень с кнопками", () => {
  it("поле остаётся блочным с фиксированным интерлиньяжем", async () => {
    await открытьЧат();

    const поле = screen.getByPlaceholderText("Сообщение…");
    // textarea по умолчанию inline-block и стоит на базовой линии: под ней
    // остаётся хвост строки в 6 px, обёртка вырастает до 50.5 при ряде,
    // выровненном по низу, и круглые кнопки уезжают на эти же 6 px ниже.
    expect(поле.className).toMatch(/(^|\s)block(\s|$)/);
    // 10 + 22 + 10 + 2 рамки = ровно 44 — высота кругов и дорожки записи.
    expect(поле.className).toContain("leading-[22px]");
    expect(поле.className).toContain("py-2.5");
  });
});
