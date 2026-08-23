/**
 * Вход в полный профиль с экрана «кто лайкнул»: тап по карточке открывает
 * ProfileSheet, и ответить (лайк/пропуск) можно прямо оттуда — решение
 * больше не принимается по одному кадру (аудит, блок «Продукт»).
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Likes from "../Likes";
import * as api from "../../lib/api";
import { useStore } from "../../lib/store";

function лайкнувшая(): api.UserProfile {
  return {
    id: "u-anya",
    display_name: "Аня",
    age: 24,
    bio: "Люблю горы и старое кино",
    gender: "female",
    city: "Москва",
    photos: ["https://x/1.jpg"],
    interests: ["кино", "горы", "джаз"],
    looking_for: "",
    is_incognito: false,
    is_locked: false,
    like_message: "Привет!",
  } as api.UserProfile;
}

function пустойТоп(): api.LeaderboardOut {
  return {
    window_days: 7,
    period: "week",
    entries: [],
    my_place: null,
    my_likes: 0,
    my_place_exact: false,
  };
}

async function открытьЛайки() {
  useStore.setState({ token: "test-token" });
  vi.spyOn(api, "getLikesReceived").mockResolvedValue([лайкнувшая()]);
  vi.spyOn(api, "getLeaderboard").mockResolvedValue(пустойТоп());

  render(
    <MemoryRouter>
      <Likes />
    </MemoryRouter>
  );
  await screen.findByText("Аня");
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useStore.setState({ token: "test-token" });
});

describe("Лайки → полный профиль", () => {
  it("тап по карточке открывает профиль с био и всеми интересами", async () => {
    await открытьЛайки();

    // В тайле био не видно — оно появляется только в полном профиле
    expect(screen.queryByText(/Люблю горы/)).toBeNull();

    fireEvent.click(screen.getByLabelText("Профиль Аня"));

    expect(await screen.findByRole("dialog", { name: "Профиль Аня" })).toBeInTheDocument();
    expect(screen.getByText(/Люблю горы и старое кино/)).toBeInTheDocument();
    for (const и of ["кино", "горы", "джаз"]) {
      expect(screen.getByText(и)).toBeInTheDocument();
    }
  });

  it("«Лайк» из шторки отвечает на симпатию и закрывает профиль", async () => {
    const like = vi
      .spyOn(api, "likeProfile")
      .mockResolvedValue({ matched: false } as any);

    await открытьЛайки();
    fireEvent.click(screen.getByLabelText("Профиль Аня"));
    await screen.findByRole("dialog", { name: "Профиль Аня" });

    // В шторке кнопка подписана словом — тайловая зовётся «Лайк Аня»
    fireEvent.click(screen.getByRole("button", { name: "Лайк" }));

    await waitFor(() => expect(like).toHaveBeenCalledWith("u-anya", "like"));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Профиль Аня" })).toBeNull()
    );
    // Карточка ушла из сетки — на неё уже ответили
    expect(screen.queryByLabelText("Профиль Аня")).toBeNull();
  });
});
