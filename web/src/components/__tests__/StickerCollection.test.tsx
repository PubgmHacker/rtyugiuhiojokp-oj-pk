/**
 * Коллекция — второй цикл возврата в продукт: смысл в том, что видно и
 * собранное, и НЕсобранное. Показывать только свои наклейки значит не
 * показать, что собирать, и кейс снова превращается в раздачу расходников.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, act } from "@testing-library/react";
import StickerCollection from "../StickerCollection";
import * as api from "../../lib/api";

const наклейка = (code: string, owned: number, rarity = "common"): api.Sticker => ({
  code,
  title: `Наклейка ${code}`,
  rarity,
  rarity_title: rarity,
  image: `/stickers/${code}.svg`,
  owned,
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Коллекция наклеек", () => {
  it("показывает и собранные, и ещё не выпавшие", async () => {
    vi.spyOn(api, "getStickers").mockResolvedValue({
      stickers: [наклейка("sun", 2), наклейка("dawn", 0, "legend")],
      owned: 1,
      total: 2,
      selected: null,
    });

    render(<StickerCollection />);

    await waitFor(() => expect(screen.getByText("1 из 2")).toBeInTheDocument());

    // Обе ячейки на месте: пустая — половина смысла коллекции
    expect(screen.getByLabelText(/Наклейка sun/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Наклейка dawn — ещё не выпала/)).toBeInTheDocument();

    // Счётчик повторов виден, иначе непонятно, что дубликаты копятся
    expect(screen.getByText("×2")).toBeInTheDocument();
  });

  it("не даёт выбрать наклейку, которой нет", async () => {
    const выбор = vi.spyOn(api, "selectSticker");
    vi.spyOn(api, "getStickers").mockResolvedValue({
      stickers: [наклейка("dawn", 0, "legend")],
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

  it("честно сообщает о сбое загрузки", async () => {
    vi.spyOn(api, "getStickers").mockRejectedValue(new Error("нет сети"));

    render(<StickerCollection />);

    // Пустая сетка вместо ошибки читалась бы как «коллекция пуста»
    await waitFor(() =>
      expect(screen.getByText("Не удалось загрузить")).toBeInTheDocument()
    );
  });
});
