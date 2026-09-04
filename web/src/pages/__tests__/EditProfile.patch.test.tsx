/**
 * Точечное редактирование анкеты: в PATCH уходит только изменённое.
 *
 * Смысл экрана /edit — не гонять человека одиннадцатью шагами онбординга
 * ради одного поля. Значит, главный контракт не «поля рисуются», а «правка
 * одного поля отправляет ровно одно поле»: пересылка всей анкеты целиком
 * втихую перезаписала бы то, что человек менял с другого устройства, и
 * прогнала бы нетронутые тексты через модерацию заново.
 *
 * Второй контракт — рост: это единственное место в продукте, где его можно
 * СТЕРЕТЬ. Пустое поле обязано уехать явным `height_cm: null` (сервер
 * принимает null ровно для сбрасываемых полей — api/tests/test_profile_edit.py
 * держит серверную половину этого рукопожатия).
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import EditProfile from "../EditProfile";
import * as api from "../../lib/api";
import { useStore } from "../../lib/store";

/** Полная анкета в сторе: экран сеет поля из неё без походов на сервер. */
function анкета(over: Partial<api.UserProfile> = {}): api.UserProfile {
  return {
    id: "u-me",
    display_name: "Аня",
    age: 24,
    bio: "люблю кино",
    gender: "female",
    city: "Москва",
    photos: ["https://cdn/1.jpg"],
    interests: ["кино"],
    looking_for: "any",
    goal: "",
    relation_type: "",
    subculture: "",
    mbti: "",
    height_cm: 170,
    is_incognito: false,
    ...over,
  } as api.UserProfile;
}

function подготовить(over: Partial<api.UserProfile> = {}) {
  const база = анкета(over);
  useStore.setState({ token: "test-token", user: база });
  const patch = vi.spyOn(api, "updateMyProfile").mockResolvedValue(база);
  return { patch };
}

function открыть(путь = "/edit") {
  render(
    <MemoryRouter initialEntries={[путь]}>
      <EditProfile />
    </MemoryRouter>
  );
}

// Подпись кнопки зависит от состояния: без правок сохранять нечего, и она
// прямо это говорит вместо мёртвого «Сохранить». Локатор берёт подпись
// параметром — так тест заодно закрепляет, что именно кнопка сообщает.
const сохранить = (name: string = "Сохранить") =>
  screen.getByRole("button", { name });

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useStore.setState({ token: "test-token", user: undefined });
});

describe("экран редактирования анкеты", () => {
  it("правка одного поля отправляет ровно одно поле", async () => {
    // Пересылка всей анкеты стёрла бы правки с другого устройства и
    // прогнала бы нетронутые тексты через модерацию заново
    const { patch } = подготовить();
    открыть();

    fireEvent.change(screen.getByLabelText("О себе"), {
      target: { value: "теперь про походы" },
    });
    fireEvent.click(сохранить());

    await waitFor(() => expect(patch).toHaveBeenCalled());
    const отправлено = patch.mock.calls[0][0] as Record<string, unknown>;
    expect(отправлено).toEqual({ bio: "теперь про походы" });
  });

  it("очищенный рост уезжает явным null — иначе его не стереть никогда", async () => {
    const { patch } = подготовить({ height_cm: 170 });
    открыть();

    fireEvent.change(screen.getByLabelText("Рост в сантиметрах"), {
      target: { value: "" },
    });
    fireEvent.click(сохранить());

    await waitFor(() => expect(patch).toHaveBeenCalled());
    const отправлено = patch.mock.calls[0][0] as Record<string, unknown>;
    expect(отправлено).toEqual({ height_cm: null });
  });

  it("без правок кнопка спит — пустой PATCH не должен существовать", () => {
    подготовить();
    открыть();

    expect((сохранить("Изменений нет") as HTMLButtonElement).disabled).toBe(true);
  });

  it("испорченное поле блокирует сохранение и объясняет почему", () => {
    // Сервер отклонил бы и сам, но человек должен услышать причину
    // до отправки, а не разбирать 422
    подготовить();
    открыть();

    fireEvent.change(screen.getByLabelText("Имя"), { target: { value: "А" } });

    expect((сохранить() as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Имя — минимум 2 символа")).toBeTruthy();
  });

  it("сохранение кладёт ответ сервера в стор", async () => {
    // Профиль рисуется из стора: не обнови его — человек вернётся
    // на экран со старыми данными и решит, что правка потерялась
    const свежая = анкета({ bio: "обновлённое био" });
    const { patch } = подготовить();
    patch.mockResolvedValue(свежая);
    открыть();

    fireEvent.change(screen.getByLabelText("О себе"), {
      target: { value: "обновлённое био" },
    });
    fireEvent.click(сохранить());

    await waitFor(() =>
      expect(useStore.getState().user?.bio).toBe("обновлённое био")
    );
  });

  it("?focus= подсвечивает секцию, алиас photo ведёт к фото", async () => {
    // Ключи фокуса приходят из чек-листа заполненности и nudge-баннера
    // на «Профиле»; там поле фото зовётся photo, секция здесь — photos
    подготовить();
    открыть("/edit?focus=photo");

    await waitFor(() => {
      const секция = document.getElementById("edit-photos");
      expect(секция?.getAttribute("data-highlight")).toBe("true");
    });
  });
});
