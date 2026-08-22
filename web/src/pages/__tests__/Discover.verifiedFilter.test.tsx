/**
 * Фильтр «Только подтверждённые» в настройках поиска.
 *
 * Единственный фильтр про безопасность, а не про вкус: он отсекает не
 * «неподходящих», а тех, кто не доказал, что он на своих фото. Серверная
 * часть (SQL в api/services/matching.py и в деке бота) проверяется своими
 * тестами; здесь — путь, которым человек вообще может его включить.
 *
 * Ломается это тихо: тумблер рисуется и щёлкает, а поле не уезжает в
 * updateMyProfile — фильтр «включён» только на экране. Поэтому главная
 * проверка не «тумблер переключился», а «на сервер ушло именно то, что
 * выбрал человек», в обе стороны — включение и выключение через «Сбросить».
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { act, render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Discover from "../Discover";
import * as api from "../../lib/api";
import { useStore } from "../../lib/store";

/** Своя анкета: фильтры уже могли быть выставлены раньше. */
function анкета(filter_verified = false): api.UserProfile {
  return {
    id: "u-me",
    display_name: "Аня",
    bio: "",
    gender: "female",
    city: "Москва",
    photos: [],
    interests: [],
    looking_for: "any",
    is_incognito: false,
    filter_verified,
  } as api.UserProfile;
}

function подготовить(filter_verified = false) {
  useStore.setState({ token: "test-token", user: анкета(filter_verified) });

  // Discover при монтировании тянет деку, лимиты, квоту суперлайков, буст
  // и карту дня — всё моками, тест не про них
  vi.spyOn(api, "getDeck").mockResolvedValue([]);
  vi.spyOn(api, "getSuperlikeQuota").mockResolvedValue({
    left: 1,
    total: 1,
    is_premium: false,
  });
  vi.spyOn(api, "getDailyLimits").mockResolvedValue({
    likes_left: 10,
    likes_total: 10,
    matches_left: 3,
    matches_total: 3,
    is_premium: false,
  });
  vi.spyOn(api, "getBoost").mockResolvedValue({
    active: false,
    minutes: 30,
    left_today: 1,
    per_day: 1,
    bonus: 0,
    required_tier_name: "",
  });
  vi.spyOn(api, "getDailyCard").mockResolvedValue({
    name: "",
    meaning: "",
    advice: "",
  });

  const patch = vi
    .spyOn(api, "updateMyProfile")
    .mockResolvedValue(анкета(filter_verified));
  vi.spyOn(api, "getMyProfile").mockResolvedValue(анкета(filter_verified));
  return { patch };
}

async function открыть_фильтры() {
  render(
    <MemoryRouter>
      <Discover />
    </MemoryRouter>
  );
  fireEvent.click(screen.getByLabelText("Настройки поиска"));
  return await screen.findByRole("button", { name: /Только подтверждённые/ });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useStore.setState({ token: "test-token", user: undefined });
});

describe("фильтр «только подтверждённые»", () => {
  it("тумблер показывает значение из анкеты, доехавшей после монтирования", async () => {
    // Порядок из продакшена: Discover рисуется, пока стор ещё пуст
    // (профиль грузится), и лишь потом приходит анкета с включённым
    // фильтром. Начальное значение useState это не покрывает — лист
    // обязан пересинхронизироваться при открытии. Иначе фильтр,
    // включённый на другом устройстве, выглядел бы выключенным — и
    // «Применить» молча стёр бы его
    подготовить(true);
    useStore.setState({ user: undefined });
    render(
      <MemoryRouter>
        <Discover />
      </MemoryRouter>
    );

    act(() => {
      useStore.setState({ user: анкета(true) });
    });
    fireEvent.click(screen.getByLabelText("Настройки поиска"));
    const тумблер = await screen.findByRole("button", {
      name: /Только подтверждённые/,
    });

    expect(тумблер.getAttribute("aria-pressed")).toBe("true");
  });

  it("включение уезжает на сервер", async () => {
    const { patch } = подготовить(false);
    const тумблер = await открыть_фильтры();
    expect(тумблер.getAttribute("aria-pressed")).toBe("false");

    fireEvent.click(тумблер);
    expect(тумблер.getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Применить" }));

    await waitFor(() => expect(patch).toHaveBeenCalled());
    const отправлено = patch.mock.calls[0][0] as { filter_verified?: boolean };
    expect(отправлено.filter_verified).toBe(true);
  });

  it("«Сбросить» выключает фильтр, и выключение тоже сохраняется", async () => {
    // Симметрия обязательна: фильтр без пути назад запер бы человека в
    // пустеющей деке — снять его можно было бы только через поддержку
    const { patch } = подготовить(true);
    const тумблер = await открыть_фильтры();
    expect(тумблер.getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Сбросить" }));
    expect(тумблер.getAttribute("aria-pressed")).toBe("false");

    fireEvent.click(screen.getByRole("button", { name: "Применить" }));

    await waitFor(() => expect(patch).toHaveBeenCalled());
    const отправлено = patch.mock.calls[0][0] as { filter_verified?: boolean };
    expect(отправлено.filter_verified).toBe(false);
  });
});
