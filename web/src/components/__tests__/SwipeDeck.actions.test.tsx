/**
 * Ряд решений под карточкой.
 *
 * Кнопки съехали со снимка вниз: столбец поверх фото закрывал лицо и
 * наклейку, а четыре одинаковых серых кружка на снимке читались дёшево.
 * Переезд заодно закрепил порядок и правила, которые глазами не проверить
 * и которые ломаются тихо:
 *
 *   1. порядок слева направо — нет → письмо → лайк → суперлайк. «Нет» и
 *      «лайк» намеренно не соседи: промах пальцем стоил бы анкеты;
 *   2. на нуле суперлайк гаснет (тратить нечего), а лайк — НЕТ: его тап
 *      открывает шторку с подпиской, и это момент продажи. Серая кнопка
 *      на его месте не объясняет ничего;
 *   3. счётчик лайков показывается только на исходе (≤5): полный запас на
 *      каждой карточке был шумом, а точное число всегда есть в подписи
 *      кнопки для читалки.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import SwipeDeck from "../SwipeDeck";
import * as api from "../../lib/api";
import { useStore } from "../../lib/store";

const АНЯ: api.DeckProfile = {
  id: "u-anya",
  display_name: "Аня",
  city: "Москва",
  bio: "",
  photos: [],
  interests: [],
};

function лимиты(осталось: number): api.DailyLimits {
  return {
    likes_left: осталось,
    likes_total: 20,
    matches_left: 5,
    matches_total: 5,
    is_premium: false,
  };
}

function подготовить(лайков: number, суперлайков: number) {
  useStore.setState({ token: "test-token", deck: [АНЯ], matches: [] });
  vi.spyOn(api, "getDeck").mockResolvedValue([]);
  vi.spyOn(api, "resetDeck").mockResolvedValue(undefined as never);
  vi.spyOn(api, "recordVisit").mockResolvedValue(undefined);
  vi.spyOn(api, "getDailyLimits").mockResolvedValue(лимиты(лайков));
  vi.spyOn(api, "getSuperlikeQuota").mockResolvedValue({
    left: суперлайков,
    total: 5,
    is_premium: false,
  });
  render(
    <MemoryRouter>
      <SwipeDeck />
    </MemoryRouter>
  );
}

/** Подписи кнопок ряда в том порядке, в каком они стоят в разметке. */
function порядок() {
  return [...document.querySelectorAll("button[aria-label]")]
    .map((b) => b.getAttribute("aria-label") ?? "")
    .filter((l) => /^(Пропустить|Написать без мэтча|Лайк|Лайки на сегодня|Суперлайк)/.test(l))
    .map((l) => l.split(",")[0].split(".")[0]);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useStore.setState({ token: "test-token", deck: [], matches: [] });
});

describe("ряд решений", () => {
  it("стоит в порядке нарастающего намерения, «нет» не рядом с лайком", async () => {
    подготовить(20, 3);
    await screen.findByLabelText("Пропустить");
    await waitFor(() =>
      expect(порядок()).toEqual([
        "Пропустить",
        "Написать без мэтча",
        "Лайк",
        "Суперлайк",
      ])
    );
  });

  it("на нуле гасит суперлайк, но не лайк", async () => {
    подготовить(0, 0);
    const супер = await screen.findByLabelText("Суперлайки закончились");
    await waitFor(() => expect(супер).toBeDisabled());
    // Лайк остаётся живым: его тап — вход в подписку, а не отказ
    expect(screen.getByLabelText("Лайки на сегодня закончились")).toBeEnabled();
  });

  it("показывает счётчик лайков только на исходе", async () => {
    подготовить(20, 3);
    await screen.findByLabelText(/^Лайк, осталось 20/);
    // Полный запас — не новость: на кнопке ничего не пишем
    expect(screen.queryByText("20")).toBeNull();
    cleanup();
    vi.restoreAllMocks();

    подготовить(3, 3);
    await screen.findByLabelText(/^Лайк, осталось 3/);
    // Три штуки — уже предупреждение: число выходит на кнопку
    await waitFor(() => expect(screen.getAllByText("3").length).toBeGreaterThan(0));
  });
});
