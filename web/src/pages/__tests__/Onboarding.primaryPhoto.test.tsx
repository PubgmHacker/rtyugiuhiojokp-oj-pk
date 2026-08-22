/**
 * Выбор главного фото.
 *
 * `photos[0]` — единственное фото, которое видят на карточке в деке, в
 * лайках, в списке чатов и в «Гостях». Остальные пять открываются только
 * тому, кто уже задержался на анкете, — то есть решение «свайпнуть вправо»
 * принимается по первому снимку и почти ни по чему больше.
 *
 * До кнопки «Главным» порядок задавался порядком загрузки: чтобы поставить
 * вперёд третий снимок, надо было удалить два первых и залить их заново,
 * каждый — через повторную AI-проверку, которая может и отказать. Люди
 * этого не делают: они остаются с неудачным главным фото. У Tinder, Bumble
 * и Hinge порядок меняется перетаскиванием с первого дня.
 *
 * Тест держит три вещи, каждая из которых ломается тихо (интерфейс во всех
 * случаях выглядит правильно, расходится только порядок массива):
 *   1. нажатое фото встаёт первым;
 *   2. остальные сохраняют свой относительный порядок — иначе «повысил
 *      одно» молча перемешало бы всю галерею;
 *   3. на сервер уезжает именно новый порядок, а не тот, что был на экране
 *      до нажатия.
 */

import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Onboarding from "../Onboarding";
import * as api from "../../lib/api";
import { useStore } from "../../lib/store";

const ФОТО = ["https://cdn/a.jpg", "https://cdn/b.jpg", "https://cdn/c.jpg"];

/** Анкета с тремя фото: человек правит уже заполненный профиль. */
function анкета(photos = ФОТО): api.UserProfile {
  return {
    id: "u-me",
    display_name: "Аня",
    bio: "о себе",
    gender: "female",
    age: 27,
    city: "Москва",
    photos,
    interests: ["Кино"],
    looking_for: "male",
    is_incognito: false,
    is_verified: false,
  } as api.UserProfile;
}

function подготовить(photos = ФОТО) {
  useStore.setState({ token: "test-token", user: анкета(photos) });
  const patch = vi
    .spyOn(api, "updateMyProfile")
    .mockResolvedValue(анкета(photos));
  vi.spyOn(api, "getMyProfile").mockResolvedValue(анкета(photos));
  return { patch };
}

function показать() {
  render(
    <MemoryRouter>
      <Onboarding />
    </MemoryRouter>
  );
}

/** Перейти на шаг фото: он третий с конца в STEPS, идём точками прогресса. */
async function на_шаг_фото() {
  // Шаги листаются кнопкой «Далее»; фото — шестой шаг (name, age, gender,
  // lookingFor, city, photos). Нажимаем ровно столько раз.
  for (let i = 0; i < 5; i++) {
    const далее = await screen.findByRole("button", { name: /Далее|Продолжить/ });
    fireEvent.click(далее);
  }
  await screen.findByText("Добавьте фото");
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useStore.setState({ token: "test-token", user: undefined });
  localStorage.clear();
});

describe("главное фото", () => {
  it("нажатое фото становится первым, остальные сохраняют порядок", async () => {
    подготовить();
    показать();
    await на_шаг_фото();

    const кнопки = screen.getAllByLabelText("Сделать главным фото");
    // Три фото — значит первое уже главное, повысить можно два
    expect(кнопки).toHaveLength(2);

    // Повышаем третье (индекс 1 среди «не главных»)
    fireEvent.click(кнопки[1]);

    // Через DOM, а не getAllByRole("img"): у декоративных снимков alt="",
    // поэтому их роль — presentation, и по роли "img" они не находятся
    const снимки = () =>
      [...document.querySelectorAll<HTMLImageElement>("img[src^='https://cdn/']")].map(
        (el) => el.getAttribute("src")
      );

    await waitFor(() =>
      expect(снимки()).toEqual([ФОТО[2], ФОТО[0], ФОТО[1]])
    );
  });

  it("на сервер уходит новый порядок фото", async () => {
    const { patch } = подготовить();
    показать();
    await на_шаг_фото();

    fireEvent.click(screen.getAllByLabelText("Сделать главным фото")[1]);
    await waitFor(() =>
      expect(screen.getAllByLabelText("Сделать главным фото")).toHaveLength(2)
    );

    // Доходим до конца и сохраняем
    for (let i = 0; i < 20; i++) {
      const далее = screen.queryAllByRole("button", {
        name: /Далее|Продолжить|Готово|Сохранить|Начать/,
      });
      if (!далее.length) break;
      fireEvent.click(далее[далее.length - 1]);
      const принять = screen.queryByRole("button", { name: /Принимаю|Согласен/ });
      if (принять) fireEvent.click(принять);
    }

    await waitFor(() => expect(patch).toHaveBeenCalled());
    const отправлено = patch.mock.calls[0][0] as { photos: string[] };
    expect(отправлено.photos).toEqual([ФОТО[2], ФОТО[0], ФОТО[1]]);
  });

  it("у единственного фото повышать нечего", async () => {
    подготовить([ФОТО[0]]);
    показать();
    await на_шаг_фото();

    // Кнопка «Главным» на одном фото была бы обманом: нажимать её незачем,
    // а её присутствие намекает, что что-то не так с текущим порядком
    expect(screen.queryByLabelText("Сделать главным фото")).toBeNull();
  });
});
