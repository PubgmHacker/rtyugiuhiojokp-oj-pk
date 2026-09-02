/**
 * Коллекция — второй цикл возврата в продукт: смысл в том, что видно и
 * собранное, и НЕсобранное. Показывать только свои наклейки значит не
 * показать, что собирать, и кейс снова превращается в раздачу расходников.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, act } from "@testing-library/react";
import StickerCollection, { группировать } from "../StickerCollection";
import * as api from "../../lib/api";

const наклейка = (
  code: string,
  owned: number,
  rarity = "common",
  set = "keropi"
): api.Sticker => ({
  code,
  title: `Наклейка ${code}`,
  rarity,
  rarity_title: rarity,
  image: `/stickers/${set}/${code}.webp`,
  set,
  owned,
});

const набор = (code: string, title: string, owned: number, total: number): api.StickerSet => ({
  code,
  title,
  owned,
  total,
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Коллекция наклеек", () => {
  it("показывает и собранные, и ещё не выпавшие", async () => {
    vi.spyOn(api, "getStickers").mockResolvedValue({
      stickers: [наклейка("sun", 2), наклейка("dawn", 0, "legend")],
      sets: [набор("keropi", "Керопи", 1, 2)],
      owned: 1,
      total: 2,
      selected: null,
    });

    render(<StickerCollection />);

    await waitFor(() => expect(screen.getByText("Коллекция")).toBeInTheDocument());

    // Обе ячейки на месте: пустая — половина смысла коллекции
    expect(screen.getByLabelText(/Наклейка sun/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Наклейка dawn — ещё не выпала/)).toBeInTheDocument();

    // Счётчик повторов виден, иначе непонятно, что дубликаты копятся
    expect(screen.getByText("×2")).toBeInTheDocument();
  });

  it("раскладывает наклейки по наборам в порядке витрины", async () => {
    vi.spyOn(api, "getStickers").mockResolvedValue({
      stickers: [
        наклейка("pepe-jason", 0, "common", "halloween"),
        наклейка("keropi-yes", 1, "legend", "keropi"),
        наклейка("march-cry", 1, "common", "starrail"),
        наклейка("march-cake", 0, "rare", "starrail"),
      ],
      sets: [
        набор("keropi", "Керопи", 1, 1),
        набор("starrail", "Star Rail", 1, 2),
        набор("halloween", "Хеллоуин", 0, 1),
      ],
      owned: 2,
      total: 4,
      selected: null,
    });

    render(<StickerCollection />);

    await waitFor(() => expect(screen.getByText("Керопи")).toBeInTheDocument());

    // Заголовки групп идут как на витрине кейсов, а не по алфавиту
    const заголовки = screen
      .getAllByText(/^(Керопи|Star Rail|Хеллоуин)$/)
      .map((el) => el.textContent);
    expect(заголовки).toEqual(["Керопи", "Star Rail", "Хеллоуин"]);

    // Прогресс каждой группы считается по её наклейкам
    expect(screen.getByText("1 из 2")).toBeInTheDocument();
    expect(screen.getByText("0 из 1")).toBeInTheDocument();
  });

  it("не теряет наклейку неизвестного набора и без наборов рисует плоско", () => {
    const данные: api.StickerCollection = {
      stickers: [наклейка("a", 1, "common", "keropi"), наклейка("z", 0, "rare", "unknown")],
      sets: [набор("keropi", "Керопи", 1, 1)],
      owned: 1,
      total: 2,
      selected: null,
    };
    const группы = группировать(данные);
    expect(группы.map((г) => г.code)).toEqual(["keropi", "other"]);
    expect(группы[1].stickers.map((н) => н.code)).toEqual(["z"]);

    // Старый сервер без наборов — одна группа без заголовка
    const плоско = группировать({ ...данные, sets: [] });
    expect(плоско).toHaveLength(1);
    expect(плоско[0].title).toBe("");
    expect(плоско[0].stickers).toHaveLength(2);
  });

  it("не даёт выбрать наклейку, которой нет", async () => {
    const выбор = vi.spyOn(api, "selectSticker");
    vi.spyOn(api, "getStickers").mockResolvedValue({
      stickers: [наклейка("dawn", 0, "legend")],
      sets: [],
      owned: 0,
      total: 1,
      selected: null,
    });

    render(<StickerCollection />);

    const кнопка = await screen.findByLabelText(/ещё не выпала/);
    await act(async () => {
      кнопка.click();
    });

    // Сервер тоже это запрещает, но и в интерфейсе кнопка не должна работать:
    // иначе человек тыкает и не понимает, почему ничего не происходит
    expect(выбор).not.toHaveBeenCalled();
    expect(кнопка).toBeDisabled();
  });

  it("перечитывает коллекцию, когда растёт версия", async () => {
    const чтение = vi.spyOn(api, "getStickers").mockResolvedValue({
      stickers: [],
      sets: [],
      owned: 0,
      total: 0,
      selected: null,
    });

    const { rerender } = render(<StickerCollection версия={0} />);
    await waitFor(() => expect(чтение).toHaveBeenCalledTimes(1));

    // После открытого кейса страница поднимает версию — коллекция обязана
    // подтянуть новую наклейку без перемонтирования и скелетона
    rerender(<StickerCollection версия={1} />);
    await waitFor(() => expect(чтение).toHaveBeenCalledTimes(2));
  });

  it("честно сообщает о сбое загрузки", async () => {
    vi.spyOn(api, "getStickers").mockRejectedValue(new Error("нет сети"));

    render(<StickerCollection />);

    // Пустая сетка вместо ошибки читалась бы как «коллекция пуста»
    await waitFor(() =>
      expect(screen.getByText("Не удалось загрузить")).toBeInTheDocument()
    );
  });
});
