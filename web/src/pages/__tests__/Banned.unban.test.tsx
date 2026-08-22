/**
 * Экран «Доступ закрыт» — платная досрочная разблокировка.
 *
 * Кнопка разблокировки ведёт на внешнюю оплату (Telegram Stars в боте),
 * поэтому у неё жёсткое правило видимости: ТОЛЬКО внутри Telegram.
 * В нативной iOS-сборке ссылка из приложения на внешнюю оплату — прямое
 * нарушение App Store 3.1.1, и её появление там — релиз-блокер. Этот тест
 * и есть та страховка: сломается — падаем до, а не на ревью Apple.
 *
 * Второе, что здесь закреплено, — акцент: внутри Telegram разбан — главный
 * CTA экрана (выше и ярче «Оспорить»), а не плитка в подвале. Нарушитель
 * выбирает между «подождать до срока» и «вернуться сейчас», и платный путь
 * обязан быть виден первым.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import Banned from "../Banned";

vi.mock("../../lib/native", () => ({
  openExternal: vi.fn(),
}));
vi.mock("../../lib/haptics", () => ({
  haptic: vi.fn(),
}));

import { openExternal } from "../../lib/native";

/** Telegram Mini App отличается непустым initData — ровно это читает isInTelegram(). */
function войтиВTelegram() {
  (window as any).Telegram = { WebApp: { initData: "query_id=test" } };
}

function выйтиИзTelegram() {
  delete (window as any).Telegram;
}

afterEach(() => {
  cleanup();
  выйтиИзTelegram();
  localStorage.removeItem("sd_banned_until");
  vi.clearAllMocks();
});

describe("Banned: досрочная разблокировка", () => {
  it("в Telegram разбан — главный CTA и ведёт диплинком в бота", () => {
    войтиВTelegram();
    render(<Banned />);

    const разбан = screen.getByText(/Разблокировать сейчас/);
    // Цена на экране обязана совпадать с ботом (UNBAN_PRICE_RUB, дефолт 349)
    expect(разбан.textContent).toContain("349");

    // Акцент: разбан стоит ВЫШЕ «Оспорить» и в главном варианте (btn-torch),
    // а обжалование уходит на второй план — иначе два равных CTA
    const оспорить = screen.getByText(/Оспорить блокировку/);
    expect(
      разбан.compareDocumentPosition(оспорить) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(разбан.className).toContain("btn-torch");
    expect(оспорить.className).not.toContain("btn-torch");

    разбан.click();
    expect(openExternal).toHaveBeenCalledTimes(1);
    const url = vi.mocked(openExternal).mock.calls[0][0];
    // Диплинк ?start=unban: бан-гейт бота ответит на /start экраном
    // блокировки с кнопкой оплаты — отдельного обработчика не нужно
    expect(url).toMatch(/^https:\/\/t\.me\/.+\?start=unban$/);
  });

  it("вне Telegram кнопки нет — App Store 3.1.1", () => {
    render(<Banned />);

    expect(screen.queryByText(/Разблокировать сейчас/)).toBeNull();
    // Путь обжалования остаётся всегда: забаненный в iOS не в тупике,
    // и без разбана именно «Оспорить» — главное действие экрана
    expect(screen.getByText(/Оспорить блокировку/).className).toContain(
      "btn-torch"
    );
  });

  it("срок истёк — разбана нет и в Telegram: платить не за что", () => {
    войтиВTelegram();
    localStorage.setItem(
      "sd_banned_until",
      new Date(Date.now() - 60_000).toISOString()
    );
    render(<Banned />);

    expect(screen.queryByText(/Разблокировать сейчас/)).toBeNull();
    // Главное действие — вернуться: бан снимается первым же запросом
    expect(screen.getByText(/Вернуться в приложение/)).toBeTruthy();
  });
});
