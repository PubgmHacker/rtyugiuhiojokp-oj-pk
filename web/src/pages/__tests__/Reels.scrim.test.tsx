/**
 * Вуали ленты. Замер на белом кадре (снег, небо, белая стена — обычное
 * видео, а не выдумка) до правки: сердце 1.10:1 к своему фону, «128» —
 * 1.11:1, заголовок 1.78:1. Знаков там просто не было.
 *
 * Держим три вещи, которые ломаются молча:
 *  1. столбик действий кроет ОТДЕЛЬНЫЙ слой, а не общий низ — общий
 *     градиент до столбика не достаёт, он выше его плотной зоны;
 *  2. этот слой выше содержимого (520 при столбике в 232) — градиент
 *     обязан дойти до нуля внутри своей коробки, иначе её край режет
 *     его прямой линией поперёк кадра;
 *  3. низ ленты берёт свой токен, а не общий bg-scrim фотокарточек —
 *     у общего на высоте имени автора всего 0.28.
 */

import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Reels from "../Reels";
import * as api from "../../lib/api";
import { useStore } from "../../lib/store";

beforeEach(() => {
  (globalThis as any).IntersectionObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  (HTMLMediaElement.prototype as any).play = () => Promise.resolve();
  (HTMLMediaElement.prototype as any).pause = () => {};
  (HTMLMediaElement.prototype as any).load = () => {};
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

async function лента() {
  useStore.setState({ token: "test-token" });
  vi.spyOn(api, "recordReelView").mockResolvedValue(undefined as any);
  vi.spyOn(api, "getReels").mockResolvedValue({
    reels: [
      {
        id: "reel-1",
        author_id: "u-author",
        author_name: "Аня",
        author_age: 23,
        author_photo: "",
        video_url: "https://example.test/v.mp4",
        cover_url: "",
        caption: "Крыша, вечер",
        likes_count: 128,
        comments_count: 12,
        views_count: 0,
        liked_by_me: false,
        is_mine: false,
        is_hidden: false,
        created_at: null,
      },
    ],
    next_before: null,
  } as any);

  const { container } = render(
    <MemoryRouter>
      <Reels />
    </MemoryRouter>
  );
  await screen.findByLabelText("Ещё действия");
  return container;
}

describe("Лента — вуали держат белый кадр", () => {
  it("под столбиком действий отдельный слой, выше самого столбика", async () => {
    const container = await лента();

    const слой = container.querySelector(".bg-reel-column");
    expect(слой).not.toBeNull();
    // Высота задана явно и с запасом: спад градиента должен уместиться
    // внутри коробки, иначе вернётся прямая линия поперёк кадра
    expect(слой!.className).toContain("h-[520px]");
    expect(слой!.className).toContain("pointer-events-none");
    // Слой красит кадр, но не значки: он ниже содержимого по z
    expect(слой!.className).toContain("z-10");
  });

  it("низ ленты не берёт общий скрим фотокарточек", async () => {
    const container = await лента();

    const низ = container.querySelector(".bg-scrim-reel");
    expect(низ).not.toBeNull();
    // Слой столбика и слой подписи — разные элементы
    expect(низ).not.toBe(container.querySelector(".bg-reel-column"));
    // Общий токен фотокарточек в ленте не участвует
    expect(container.querySelector(".bg-scrim")).toBeNull();
  });
});
