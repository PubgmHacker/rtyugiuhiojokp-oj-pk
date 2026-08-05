/**
 * Комната ждёт открытия сообщений комнаты асинхронно (getRoomMessages) и
 * опрашивает их периодически (раз в 7с). Проверяем защиту от гонки: если
 * первый (более старый) запрос отвечает позже второго (более нового), его
 * результат не должен затирать уже показанные свежие сообщения —
 * см. web/src/pages/Rooms.tsx, load().
 */

import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup, act } from "@testing-library/react";
import Rooms from "../Rooms";
import * as api from "../../lib/api";

const ROOM: api.Room = {
  id: "room-1",
  slug: "test",
  title: "Тестовая комната",
  description: "",
  city: "",
  messages_today: 3,
};

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  // Аналитика открытия раздела не относится к тесту гонки — глушим сетевой
  // вызов, чтобы не засорять вывод ошибками CORS в jsdom.
  vi.spyOn(api, "recordSectionOpen").mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("Rooms/RoomChat — гонка опроса сообщений", () => {
  it("не даёт устаревшему (более старому) ответу перезаписать свежий", async () => {
    const first = deferred<{ messages: api.RoomMessage[] }>();
    const second = deferred<{ messages: api.RoomMessage[] }>();

    const getRoomMessages = vi
      .spyOn(api, "getRoomMessages")
      .mockImplementationOnce(() => first.promise as any)
      .mockImplementationOnce(() => second.promise as any);

    vi.spyOn(api, "getRooms").mockResolvedValue([ROOM]);

    render(<Rooms />);

    const roomButton = await screen.findByText("Тестовая комната");
    await act(async () => {
      fireEvent.click(roomButton);
    });

    await waitFor(() => expect(getRoomMessages).toHaveBeenCalledTimes(1));

    // Продвигаем таймер опроса на 7с, чтобы улетел второй (более новый) запрос.
    await act(async () => {
      vi.advanceTimersByTime(7000);
    });
    await waitFor(() => expect(getRoomMessages).toHaveBeenCalledTimes(2));

    // Второй (новый) запрос отвечает первым.
    await act(async () => {
      second.resolve({
        messages: [
          {
            id: "m-new",
            sender_id: "u1",
            sender_name: "Свежий",
            sender_photo: "",
            text: "новое",
            is_mine: false,
          },
        ],
      });
      await second.promise;
    });

    await waitFor(() => expect(screen.getByText("новое")).toBeInTheDocument());

    // Первый (старый) запрос отвечает позже — его результат должен быть отброшен.
    await act(async () => {
      first.resolve({
        messages: [
          {
            id: "m-old",
            sender_id: "u1",
            sender_name: "Старый",
            sender_photo: "",
            text: "старое",
            is_mine: false,
          },
        ],
      });
      await first.promise;
    });

    expect(screen.queryByText("старое")).not.toBeInTheDocument();
    expect(screen.getByText("новое")).toBeInTheDocument();
  });
});
