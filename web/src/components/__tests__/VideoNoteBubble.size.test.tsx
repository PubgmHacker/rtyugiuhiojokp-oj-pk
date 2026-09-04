/**
 * Видеокружок: компактный в переписке, крупный — когда его смотрят.
 *
 * В ленте кружок один из многих, а смотрят всегда один: развёрнутый по
 * умолчанию, он съедал экран и выглядел как вставленное видео, а не как
 * сообщение (так это и работает в Telegram — владелец на это указал).
 * Размер привязан к звуку, поэтому он же и сворачивает кружок обратно:
 * по концу записи и когда звук забирает соседнее сообщение.
 *
 * Глазами это проверяется только на живой записи, которой в демо-базе нет,
 * — поэтому проверяем стилем и подписью для чтения с экрана.
 */

import { describe, it, expect, vi, beforeAll, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import VideoNoteBubble from "../VideoNoteBubble";
import type { ChatMedia } from "../../lib/api";

const КРУЖОК: ChatMedia = {
  url: "https://x/note.mp4",
  kind: "video_note",
  duration: 12,
  shape: "circle",
};

beforeAll(() => {
  // jsdom не умеет проигрывать: без заглушки play() отдаёт undefined,
  // и .catch() на нём валит клик
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
});

afterEach(cleanup);

describe("VideoNoteBubble — размер по звуку", () => {
  it("в покое компактный и зовёт развернуть", () => {
    render(<VideoNoteBubble media={КРУЖОК} mine={false} />);
    const кружок = screen.getByRole("button");
    expect(кружок.style.width).toBe("148px");
    expect(кружок.getAttribute("aria-label")).toMatch(/развернуть и включить звук/);
  });

  it("по нажатию вырастает, по второму — сворачивается", () => {
    render(<VideoNoteBubble media={КРУЖОК} mine={false} />);
    const кружок = screen.getByRole("button");

    fireEvent.click(кружок);
    expect(кружок.style.width).toBe("min(70vw, 244px)");
    expect(кружок.getAttribute("aria-label")).toBe("Свернуть видеосообщение");

    fireEvent.click(кружок);
    expect(кружок.style.width).toBe("148px");
  });

  it("конец записи сворачивает кружок сам", () => {
    const { container } = render(<VideoNoteBubble media={КРУЖОК} mine={false} />);
    const кружок = screen.getByRole("button");
    const видео = container.querySelector("video")!;

    fireEvent.click(кружок);
    expect(кружок.style.width).toBe("min(70vw, 244px)");

    fireEvent.ended(видео);
    expect(кружок.style.width).toBe("148px");
  });
});
