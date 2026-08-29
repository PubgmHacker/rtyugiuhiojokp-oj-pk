/**
 * Успешная жалоба на ролик раньше уходила в error-канал: «Жалоба
 * отправлена» показывалась красной плашкой сбоя, и человек не понимал,
 * дошла она или нет (аудит, блок «Доверие»). Успех — зелёный notice,
 * сбой — красный error. См. handleReport в web/src/pages/Reels.tsx.
 */

import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Reels from "../Reels";
import * as api from "../../lib/api";
import { useStore } from "../../lib/store";

// jsdom не умеет ни IntersectionObserver (автоплей ленты), ни video.play —
// без заглушек экран падает на монтировании, а не на предмете теста
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

function ролик(over: Partial<api.Reel> = {}): api.Reel {
  return {
    id: "reel-1",
    author_id: "u-author",
    author_name: "Аня",
    author_age: null,
    author_photo: "",
    video_url: "https://example.test/v.mp4",
    cover_url: "",
    caption: "",
    likes_count: 0,
    comments_count: 0,
    views_count: 0,
    liked_by_me: false,
    is_mine: false,
    is_hidden: false,
    created_at: null,
    ...over,
  };
}

async function открытьЛентуИПожаловаться() {
  useStore.setState({ token: "test-token" });
  vi.spyOn(api, "getReels").mockResolvedValue({
    reels: [ролик()],
    next_before: null,
  } as any);

  render(
    <MemoryRouter>
      <Reels />
    </MemoryRouter>
  );

  fireEvent.click(await screen.findByLabelText("Пожаловаться на ролик"));
  fireEvent.click(await screen.findByText("Спам или реклама"));
}

describe("Reels — исход жалобы в правильном канале", () => {
  it("успех — зелёная плашка notice, а не красная error", async () => {
    vi.spyOn(api, "reportReel").mockResolvedValue(undefined as any);

    await открытьЛентуИПожаловаться();

    const плашка = await screen.findByText(/Жалоба отправлена/);
    // Каналы различаются рамкой: success — зелёная, danger — красная
    expect(плашка.className).toContain("text-success");
    expect(плашка.className).not.toContain("text-danger");
  });

  it("сбой — красная error с текстом", async () => {
    const e: any = new Error("HTTP 500");
    e.response = { status: 500, data: {} };
    vi.spyOn(api, "reportReel").mockRejectedValue(e);

    await открытьЛентуИПожаловаться();

    const плашка = await screen.findByText(/Не удалось отправить жалобу/);
    expect(плашка.className).toContain("text-danger");
  });

  it("показывает понятный retry, если CDN не отдал видео", async () => {
    vi.spyOn(api, "recordReelView").mockResolvedValue(undefined as any);
    const load = vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
    vi.spyOn(api, "getReels").mockResolvedValue({
      reels: [ролик()],
      next_before: null,
    } as any);

    render(
      <MemoryRouter>
        <Reels />
      </MemoryRouter>
    );

    const video = await screen.findByLabelText("Видео Аня");
    fireEvent.error(video);
    expect(await screen.findByText("Видео не удалось загрузить")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Повторить"));
    expect(load).toHaveBeenCalled();
  });
});
