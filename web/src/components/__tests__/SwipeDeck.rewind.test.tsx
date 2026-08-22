/**
 * Возврат последней карточки.
 *
 * Промах пальцем на свайпах — самая частая и самая обидная потеря в продукте:
 * анкета уезжает навсегда, и человек уже не узнает, кого пропустил. Поэтому
 * у возврата три обязательства, и каждое ломается по-своему тихо:
 *
 *   1. карточка возвращается НА ВЕРХ деки — иначе «вернул» означает «увижу
 *      когда-нибудь потом»;
 *   2. отправленный лайк реально отзывается на сервере и остатки берутся
 *      оттуда же — иначе лайк остаётся висеть у получателя, а счётчик на
 *      кнопке начинает врать;
 *   3. после мэтча возврата нет — сервер на смену решения мэтч не гасит, и
 *      кнопка оставила бы живую беседу с «развзаимненным» человеком.
 *
 * Ни одно из трёх не видно ни typecheck'ом, ни глазами: интерфейс выглядит
 * правильно во всех четырёх случаях, расходится только состояние.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import SwipeDeck from "../SwipeDeck";
import * as api from "../../lib/api";
import { useStore } from "../../lib/store";

function анкета(id: string, имя: string): api.DeckProfile {
  return {
    id,
    display_name: имя,
    city: "Москва",
    bio: "",
    photos: [],
    interests: [],
  };
}

const АНЯ = анкета("u-anya", "Аня");
const БОРИС = анкета("u-boris", "Борис");

function лимиты(осталось: number): api.DailyLimits {
  return {
    likes_left: осталось,
    likes_total: 20,
    matches_left: 5,
    matches_total: 5,
    is_premium: false,
  };
}

function квота(осталось: number): api.SuperlikeQuota {
  return { left: осталось, total: 1, is_premium: false };
}

/** Мэтч в том виде, в котором его отдаёт сервер вместе с лайком. */
function мэтч(): api.MatchResponse {
  return {
    id: "m1",
    partner: { id: АНЯ.id, display_name: АНЯ.display_name } as api.UserProfile,
  };
}

/** Общая обвязка: дека в сторе, пустая догрузка, известные остатки. */
function подготовить(дека: api.DeckProfile[], осталось = 9) {
  useStore.setState({ token: "test-token", deck: дека, matches: [] });
  // Дека короче порога предзагрузки, поэтому компонент сразу просит ещё:
  // отдаём пусто, чтобы состав деки в тесте задавали только свайпы
  vi.spyOn(api, "getDeck").mockResolvedValue([]);
  vi.spyOn(api, "resetDeck").mockResolvedValue(undefined as never);
  vi.spyOn(api, "recordVisit").mockResolvedValue(undefined);
  const limits = vi.spyOn(api, "getDailyLimits").mockResolvedValue(лимиты(осталось));
  const superlikes = vi
    .spyOn(api, "getSuperlikeQuota")
    .mockResolvedValue(квота(1));
  const like = vi
    .spyOn(api, "likeProfile")
    .mockResolvedValue({ liked: true, matched: false });
  return { like, limits, superlikes };
}

function показать() {
  render(
    <MemoryRouter>
      <SwipeDeck />
    </MemoryRouter>
  );
}

const ВЕРНУТЬ_АНЮ = "Вернуть анкету: Аня";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useStore.setState({ token: "test-token", deck: [], matches: [] });
});

describe("возврат последней карточки", () => {
  it("возвращает пропущенную анкету на верх деки", async () => {
    const { like } = подготовить([АНЯ, БОРИС]);
    показать();

    fireEvent.click(await screen.findByLabelText("Пропустить"));

    const вернуть = await screen.findByLabelText(ВЕРНУТЬ_АНЮ);
    await waitFor(() => expect(useStore.getState().deck[0].id).toBe(БОРИС.id));

    fireEvent.click(вернуть);

    // Именно на верх: анкета, которую только что пропустили по ошибке,
    // должна снова оказаться под пальцем, а не в конце очереди
    await waitFor(() => expect(useStore.getState().deck[0].id).toBe(АНЯ.id));
    expect(useStore.getState().deck.map((p) => p.id)).toEqual([АНЯ.id, БОРИС.id]);
    // Пропуск отзывать нечем: он ничего не потратил и никому не показан,
    // второго запроса быть не должно
    expect(like).toHaveBeenCalledTimes(1);
    expect(like).toHaveBeenCalledWith(АНЯ.id, "pass", "");
  });

  it("отзывает отправленный лайк и берёт остатки с сервера", async () => {
    const { like, limits, superlikes } = подготовить([АНЯ, БОРИС]);
    показать();

    fireEvent.click(await screen.findByLabelText(/^Лайк, осталось 9 на сегодня/));

    const вернуть = await screen.findByLabelText(ВЕРНУТЬ_АНЮ);
    expect(like).toHaveBeenCalledWith(АНЯ.id, "like", "");
    // Локальный счётчик ушёл вниз сразу, не дожидаясь сети
    await screen.findByLabelText(/^Лайк, осталось 8 на сегодня/);

    // Сервер вернул лайк в суточную квоту — и один суперлайк сверх неё,
    // которого локальный «плюс один» не угадал бы
    limits.mockResolvedValue(лимиты(9));
    superlikes.mockResolvedValue(квота(2));

    fireEvent.click(вернуть);

    await waitFor(() => expect(like).toHaveBeenCalledWith(АНЯ.id, "pass"));
    // Счётчик на кнопке — это и есть доказательство, что остатки перечитаны:
    // прибавленная локально единица дала бы то же 9, а суперлайк — нет
    await screen.findByLabelText(/^Лайк, осталось 9 на сегодня/);
    await screen.findByLabelText("Суперлайк, осталось 2");
    expect(limits.mock.calls.length).toBeGreaterThan(1);
    expect(useStore.getState().deck[0].id).toBe(АНЯ.id);
  });

  it("не предлагает возврат после мэтча", async () => {
    const { like } = подготовить([АНЯ, БОРИС]);
    like.mockResolvedValue({ liked: true, matched: true, match: мэтч() });
    показать();

    fireEvent.click(await screen.findByLabelText(/^Лайк, осталось 9 на сегодня/));

    // Ждём подтверждения, что свайп доехал до конца: без этого «кнопки нет»
    // означало бы всего лишь «ответ ещё не пришёл»
    await waitFor(() => expect(useStore.getState().matches).toHaveLength(1));
    expect(screen.queryByLabelText(ВЕРНУТЬ_АНЮ)).toBeNull();
  });

  it("остаётся доступен, когда после свайпа дека опустела", async () => {
    // Самый частый случай промаха — последняя анкета: рейла с кнопками уже
    // нет, и без возврата на пустом экране исправить решение нечем
    const { like } = подготовить([АНЯ]);
    показать();

    fireEvent.click(await screen.findByLabelText("Пропустить"));

    const вернуть = await screen.findByRole("button", { name: "Вернуть последнюю" });
    expect(useStore.getState().deck).toHaveLength(0);

    fireEvent.click(вернуть);

    await waitFor(() => expect(useStore.getState().deck[0].id).toBe(АНЯ.id));
    expect(like).toHaveBeenCalledTimes(1);
  });
});
