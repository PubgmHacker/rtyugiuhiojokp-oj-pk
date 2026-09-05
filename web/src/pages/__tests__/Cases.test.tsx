/**
 * Экран кейсов: три плитки, одна квота, дроп — только оформление анкеты.
 *
 * Что закреплено и почему:
 *  - открывается именно выбранный кейс (код уходит на сервер) — наборы
 *    разные, «какой-нибудь» кейс сломал бы коллекционирование;
 *  - после дропа плитка растёт на единицу сразу, а квота списывается на
 *    всех плитках: попытки общие, и вторая кнопка не должна остаться живой;
 *  - выпавшее надевается в один тап без похода в коллекцию;
 *  - повтор не растит прогресс — иначе «Собрано 6 из 5»;
 *  - без подписки — замки и ссылка на тарифы, кнопок «Открыть» нет;
 *  - текст ошибки сервера показывается как есть: 429 и «сначала анкета»
 *    объясняют, что делать, а «не удалось» — нет.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Cases from "../Cases";
import type { CaseOpenResult, CaseState, Sticker } from "../../lib/api";

vi.mock("../../lib/api", () => ({
  getCaseState: vi.fn(),
  openCase: vi.fn(),
  selectSticker: vi.fn(),
  selectDecor: vi.fn(),
  getStickers: vi.fn(),
  getDecor: vi.fn(),
}));
vi.mock("../../lib/haptics", () => ({ haptic: vi.fn() }));
vi.mock("../../lib/useSectionOpen", () => ({ useSectionOpen: vi.fn() }));

import {
  getCaseState,
  openCase,
  selectSticker,
  selectDecor,
  getStickers,
  getDecor,
} from "../../lib/api";

function наклейка(code: string, title: string, rarity = "common", set = "keropi"): Sticker {
  return {
    code,
    title,
    rarity,
    rarity_title: rarity === "rare" ? "Редкая" : "Обычная",
    image: `/stickers/${set}/${code}.webp`,
    set,
    owned: 1,
  };
}

/** Витрина как с сервера: одна попытка, «Керопи» начат, «Хеллоуин» собран. */
function состояние(patch: Partial<CaseState> = {}): CaseState {
  return {
    left: 1,
    per_month: 1,
    resets_at: "2026-10-01T00:00:00Z",
    rewards: [
      { code: "sticker", title: "Наклейка набора", amount: 1, chance_percent: 80 },
      { code: "decor", title: "Обложка анкеты", amount: 1, chance_percent: 20 },
    ],
    cases: [
      {
        code: "keropi",
        title: "Керопи",
        hint: "Лягушонок Sanrio: пять наклеек",
        accent: "#7ed957",
        total: 5,
        owned: 1,
        preview: ["/stickers/keropi/keropi-desk.webp"],
        rarity_chances: { common: 60, rare: 20, epic: 20 },
      },
      {
        code: "starrail",
        title: "Star Rail",
        hint: "Март 7, Зеле, Пом-Пом и другие",
        accent: "#7aa2ff",
        total: 28,
        owned: 0,
        preview: [],
        rarity_chances: { common: 50, rare: 30, epic: 15, legend: 5 },
      },
      {
        code: "halloween",
        title: "Хеллоуин",
        hint: "Пепе в костюмах злодеев из хорроров",
        accent: "#ff8a3c",
        total: 6,
        owned: 6,
        preview: [],
        rarity_chances: { common: 50, rare: 50 },
      },
    ],
    required_tier_name: "Plus",
    ...patch,
  };
}

function дроп(patch: Partial<CaseOpenResult> = {}): CaseOpenResult {
  return {
    reward: {
      code: "sticker",
      title: "Наклейка набора",
      amount: 1,
      chance_percent: 80,
      sticker: наклейка("keropi-bike", "Керопи на велике", "rare"),
    },
    case: "keropi",
    left: 0,
    per_month: 1,
    resets_at: "2026-10-01T00:00:00Z",
    duplicate: false,
    ...patch,
  };
}

function отрисовать() {
  return render(
    <MemoryRouter>
      <Cases />
    </MemoryRouter>
  );
}

/*
 * Витрина кейсов, наклейки и обложки грузятся тремя независимыми запросами.
 * Дождавшись первого, счётчик второго нельзя проверять напрямую: на занятой
 * машине он ещё в полёте, и тест падает без единой правки в коде экрана —
 * поэтому ниже везде waitFor вокруг самого счётчика.
 */
async function дождатьсяВитрины() {
  await screen.findByRole("region", { name: "Кейс «Керопи»" });
}

/** Баннер выигрыша — по его тексту: role="status" есть и у спиннера в кнопке. */
async function дождатьсяВыигрыша(): Promise<HTMLElement> {
  const заголовок = await screen.findByText(/^Выпало:/);
  return заголовок.closest('[role="status"]') as HTMLElement;
}

beforeEach(() => {
  vi.mocked(getCaseState).mockResolvedValue(состояние());
  vi.mocked(getStickers).mockResolvedValue({
    stickers: [],
    sets: [],
    owned: 0,
    total: 0,
    selected: null,
  });
  vi.mocked(getDecor).mockResolvedValue({ decors: [], selected: null, owned: 0, total: 0 });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Cases", () => {
  it("показывает три кейса с прогрессом, шансами и общей квотой", async () => {
    отрисовать();
    await дождатьсяВитрины();

    expect(screen.getByText("Попыток: 1")).toBeInTheDocument();
    expect(screen.getByText(/общие на все кейсы/)).toBeInTheDocument();

    const керопи = screen.getByRole("region", { name: "Кейс «Керопи»" });
    expect(within(керопи).getByText("Собрано 1 из 5")).toBeInTheDocument();
    // Подпись редкости — вложенный span, процент лежит в чипе-родителе
    expect(within(керопи).getByText(/эпические/).parentElement).toHaveTextContent("20%");
    // Веер-приманка — картинки набора
    expect(керопи.querySelector('img[src="/stickers/keropi/keropi-desk.webp"]')).not.toBeNull();

    const starRail = screen.getByRole("region", { name: "Кейс «Star Rail»" });
    expect(within(starRail).getByText("Собрано 0 из 28")).toBeInTheDocument();
    expect(within(starRail).getByText(/легендарные/).parentElement).toHaveTextContent("5%");

    const хеллоуин = screen.getByRole("region", { name: "Кейс «Хеллоуин»" });
    expect(within(хеллоуин).getByText(/Набор собран/)).toBeInTheDocument();

    expect(screen.getAllByRole("button", { name: /^Открыть кейс/ })).toHaveLength(3);
    // Шанс обложки — последним чипом на самой плитке, а не отдельной таблицей
    // внизу экрана: чипы плитки в сумме дают 100%, и перемножать две таблицы
    // процентов в уме человеку больше не нужно.
    expect(within(керопи).getByText(/обложка/).parentElement).toHaveTextContent("20%");
    expect(screen.queryByText("Наклейка набора")).toBeNull();
    // Расходников в кейсах нет — только наклейки набора и обложки анкеты
    expect(screen.queryByText(/суперлайк/i)).toBeNull();
    expect(screen.queryByText(/буст/i)).toBeNull();
  });

  it("открывает выбранный кейс, растит его плитку и списывает общую квоту", async () => {
    vi.mocked(openCase).mockResolvedValue(дроп());
    отрисовать();
    await дождатьсяВитрины();
    await waitFor(() => expect(getStickers).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Открыть кейс «Керопи»" }));

    expect(openCase).toHaveBeenCalledWith("keropi");
    const баннер = await дождатьсяВыигрыша();
    expect(баннер).toHaveTextContent("Выпало: Керопи на велике");
    expect(баннер).toHaveTextContent("Кейс «Керопи»");
    expect(баннер).toHaveTextContent("новая в коллекции");
    expect(баннер).toHaveTextContent("Редкая");
    expect(баннер.querySelector('img[src="/stickers/keropi/keropi-bike.webp"]')).not.toBeNull();

    // Плитка выросла сразу, не дожидаясь перечитывания
    const керопи = screen.getByRole("region", { name: "Кейс «Керопи»" });
    expect(within(керопи).getByText("Собрано 2 из 5")).toBeInTheDocument();

    // Квота общая: кончилась — заперты все три плитки, дата обновления видна
    expect(screen.getByText("Попыток: 0")).toBeInTheDocument();
    expect(screen.getByText(/обновятся/)).toBeInTheDocument();
    for (const кнопка of screen.getAllByRole("button", { name: /^Открыть кейс/ })) {
      expect(кнопка).toBeDisabled();
      expect(кнопка).toHaveTextContent("Попытки закончились");
    }

    // Коллекция ниже перечитана: наклейка появится в ней без перезагрузки
    await waitFor(() => expect(getStickers).toHaveBeenCalledTimes(2));
  });

  it("надевает выпавшую наклейку в один тап", async () => {
    vi.mocked(openCase).mockResolvedValue(дроп());
    vi.mocked(selectSticker).mockResolvedValue({
      stickers: [],
      sets: [],
      owned: 1,
      total: 5,
      selected: "keropi-bike",
    });
    отрисовать();
    await дождатьсяВитрины();

    fireEvent.click(screen.getByRole("button", { name: "Открыть кейс «Керопи»" }));
    const надеть = await screen.findByRole("button", { name: "Надеть" });
    fireEvent.click(надеть);

    expect(selectSticker).toHaveBeenCalledWith("keropi-bike");
    expect(selectDecor).not.toHaveBeenCalled();
    await screen.findByText("Надето");
    expect(screen.getByRole("button", { name: /Надето/ })).toBeDisabled();
  });

  it("обложка выпадает из любого кейса и надевается через свой сервис", async () => {
    vi.mocked(openCase).mockResolvedValue(
      дроп({
        case: "starrail",
        reward: {
          code: "decor",
          title: "Обложка анкеты",
          amount: 1,
          chance_percent: 20,
          decor: {
            code: "frost",
            title: "Иней",
            rarity: "rare",
            rarity_title: "Редкая",
            unlocked: true,
          },
        },
      })
    );
    vi.mocked(selectDecor).mockResolvedValue({ decors: [], selected: "frost", owned: 1, total: 5 });
    отрисовать();
    await дождатьсяВитрины();
    await waitFor(() => expect(getDecor).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Открыть кейс «Star Rail»" }));

    const баннер = await дождатьсяВыигрыша();
    expect(баннер).toHaveTextContent("Выпало: Иней");
    expect(баннер).toHaveTextContent("обложка анкеты");
    // Обложка — не наклейка: прогресс набора не трогаем
    const starRail = screen.getByRole("region", { name: "Кейс «Star Rail»" });
    expect(within(starRail).getByText("Собрано 0 из 28")).toBeInTheDocument();
    // Витрина обложек перечитана
    await waitFor(() => expect(getDecor).toHaveBeenCalledTimes(2));

    fireEvent.click(screen.getByRole("button", { name: "Надеть" }));
    expect(selectDecor).toHaveBeenCalledWith("frost");
    expect(selectSticker).not.toHaveBeenCalled();
    await screen.findByText("Надето");
  });

  it("повтор наклейки не растит прогресс плитки", async () => {
    vi.mocked(openCase).mockResolvedValue(дроп({ duplicate: true }));
    отрисовать();
    await дождатьсяВитрины();

    fireEvent.click(screen.getByRole("button", { name: "Открыть кейс «Керопи»" }));

    const баннер = await дождатьсяВыигрыша();
    expect(баннер).toHaveTextContent("такая уже есть");
    const керопи = screen.getByRole("region", { name: "Кейс «Керопи»" });
    expect(within(керопи).getByText("Собрано 1 из 5")).toBeInTheDocument();
  });

  it("без подписки кейсы заперты, а кнопка ведёт на тарифы", async () => {
    vi.mocked(getCaseState).mockResolvedValue(состояние({ left: 0, per_month: 0 }));
    отрисовать();
    await дождатьсяВитрины();

    expect(screen.getByText("Попытки даются с подпиской Plus")).toBeInTheDocument();
    expect(screen.getAllByText("Открывается с подпиской")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: /^Открыть кейс/ })).toBeNull();
    expect(screen.getByRole("link", { name: /Оформить подписку/ })).toHaveAttribute(
      "href",
      "/plans"
    );
  });

  it("показывает текст ошибки сервера как есть", async () => {
    vi.mocked(openCase).mockRejectedValue({
      response: { status: 400, data: { detail: "Сначала заполните анкету" } },
    });
    отрисовать();
    await дождатьсяВитрины();

    fireEvent.click(screen.getByRole("button", { name: "Открыть кейс «Керопи»" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Сначала заполните анкету");
    // Квота не списана: попытка не состоялась
    expect(screen.getByText("Попыток: 1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Открыть кейс «Керопи»" })).toBeEnabled();
  });

  it("при сбое первой загрузки даёт повторить, а не вечные скелетоны", async () => {
    vi.mocked(getCaseState)
      .mockRejectedValueOnce(new Error("сеть"))
      .mockResolvedValueOnce(состояние());
    отрисовать();

    await screen.findByText("Не удалось загрузить");
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));

    await дождатьсяВитрины();
    expect(getCaseState).toHaveBeenCalledTimes(2);
  });
});
