/**
 * Экран «кто меня лайкнул» — главный платный гейт продукта.
 *
 * Требования к нему противоположные и оба обязательные: имя и фото
 * бесплатному показывать нельзя (иначе подписку не за что покупать), но
 * количество показать НУЖНО — пустой экран заставит думать, что лайков нет,
 * и покупать станет незачем.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Likes from "../Likes";
import * as api from "../../lib/api";
import { useStore } from "../../lib/store";

function закрытая(id: string): api.UserProfile {
  // Ровно то, что присылает сервер бесплатному: ни имени, ни фото
  return {
    id,
    display_name: "",
    bio: "",
    gender: "",
    city: "",
    photos: [],
    interests: [],
    looking_for: "",
    is_incognito: false,
    is_locked: true,
  } as api.UserProfile;
}

/** Топ недели этому экрану не важен, но тип обязан совпадать с настоящим. */
function пустойТоп(): api.LeaderboardOut {
  return {
    window_days: 7,
    entries: [],
    my_place: null,
    my_likes: 0,
    my_place_exact: false,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useStore.setState({ token: "test-token" });
});

describe("Кто меня лайкнул — платный гейт", () => {
  it("бесплатному показывает число, но не имена", async () => {
    vi.spyOn(api, "getLikesReceived").mockResolvedValue([
      закрытая("u1"),
      закрытая("u2"),
      закрытая("u3"),
    ]);
    vi.spyOn(api, "getLeaderboard").mockResolvedValue(пустойТоп());

    render(
      <MemoryRouter>
        <Likes />
      </MemoryRouter>
    );

    // Число видно: иначе непонятно, за что платить
    await waitFor(() =>
      expect(screen.getByText("3 человека")).toBeInTheDocument()
    );

    // А открыть можно только в Plus — и таких заглушек столько же, сколько лайков
    const заглушки = await screen.findAllByText("Открыть в Plus");
    expect(заглушки).toHaveLength(3);
  });

  it("подписчику показывает имена без замков", async () => {
    vi.spyOn(api, "getLikesReceived").mockResolvedValue([
      {
        ...закрытая("u1"),
        is_locked: false,
        display_name: "Аня",
        photos: ["https://x/1.jpg"],
      } as api.UserProfile,
    ]);
    vi.spyOn(api, "getLeaderboard").mockResolvedValue(пустойТоп());

    render(
      <MemoryRouter>
        <Likes />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText("Аня")).toBeInTheDocument());
    // Гейт не должен закрывать то, что уже оплачено
    expect(screen.queryByText("Открыть в Plus")).not.toBeInTheDocument();
  });
});
