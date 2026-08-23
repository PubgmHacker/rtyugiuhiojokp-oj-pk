/**
 * Витрина тарифов: одно поле на промокод И подарочный код.
 *
 * Человеку всё равно, из поста его код или от друга, поэтому второго поля
 * на витрине нет. Закреплён каскад — тот же, что в боте
 * (bot/handlers/premium.py::promo_code_received):
 *  - промокод принят → подарок даже не дёргается;
 *  - промо ответило 404 → тот же ввод уходит в /gifts/redeem;
 *  - оба промаха → «нет такого кода — ни промокода, ни подарочного»;
 *  - содержательный отказ подарка (уровень уже выше) → текст сервера,
 *    как есть: там объяснение, что код цел.
 * Сломается каскад — подарочные коды снова станут деньгами без пути
 * активации, ровно той дырой, из-за которой /gifts/redeem появился.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import Plans from "../Plans";

vi.mock("../../lib/api", () => ({
  activatePromo: vi.fn(),
  redeemGift: vi.fn(),
  getPlans: vi.fn(),
  getMyProfile: vi.fn(),
}));
vi.mock("../../lib/haptics", () => ({ haptic: vi.fn() }));
vi.mock("../../lib/native", () => ({
  isNative: () => false,
  openExternal: vi.fn(),
}));
vi.mock("../../lib/iap", () => ({
  isPurchaseAvailable: vi.fn(async () => false),
  loadProducts: vi.fn(async () => []),
  purchaseGift: vi.fn(),
  purchasePremium: vi.fn(),
  restorePurchases: vi.fn(),
}));
vi.mock("../../lib/store", () => ({
  useStore: () => ({ user: { id: "u1" }, setUser: vi.fn() }),
}));

import { activatePromo, redeemGift, getPlans, getMyProfile } from "../../lib/api";

/** Минимальная витрина: один уровень, один план — полю кода больше не надо. */
const ВИТРИНА = {
  current_tier: "free",
  tiers: [
    {
      tier: "plus",
      name: "Plus",
      superlikes: 5,
      perks: ["Безлимитные лайки"],
      plans: [
        {
          code: "plus_1m",
          tier: "plus",
          title: "1 месяц",
          months: 1,
          price_rub: 299,
          price_per_month: 299,
          price_per_day: 10,
          appstore_id: "sd.plus.1m",
        },
      ],
    },
  ],
};

/** 404/409 в форме axios-ошибки — ровно то, что читает PromoField. */
function отказ(status: number, detail?: string) {
  return Object.assign(new Error(`HTTP ${status}`), {
    response: { status, data: detail ? { detail } : {} },
  });
}

async function открытьВитрину() {
  render(<Plans />);
  // Поле кода появляется после загрузки витрины
  return await screen.findByPlaceholderText("ПРОМОКОД");
}

beforeEach(() => {
  vi.mocked(getPlans).mockResolvedValue(ВИТРИНА as any);
  vi.mocked(getMyProfile).mockResolvedValue({ id: "u1" } as any);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Plans: одно поле на промокод и подарочный код", () => {
  it("успешный промокод не дёргает подарочный каскад", async () => {
    vi.mocked(activatePromo).mockResolvedValue({
      tier: "plus",
      days: 7,
      plan: "plus",
      expires_at: "2026-08-29T00:00:00",
    });
    const поле = await открытьВитрину();

    fireEvent.change(поле, { target: { value: "LETO" } });
    fireEvent.click(screen.getByText("Активировать"));

    await screen.findByText(/Промокод принят.*2026-08-29/);
    expect(redeemGift).not.toHaveBeenCalled();
  });

  it("404 от промо активирует тот же ввод как подарочный код", async () => {
    vi.mocked(activatePromo).mockRejectedValue(отказ(404, "Такого промокода нет"));
    vi.mocked(redeemGift).mockResolvedValue({
      tier: "ultra",
      months: 3,
      plan: "ultra",
      expires_at: "2026-11-22T00:00:00",
    });
    const поле = await открытьВитрину();

    fireEvent.change(поле, { target: { value: "wxyz-2345" } });
    fireEvent.click(screen.getByText("Активировать"));

    await screen.findByText(/Подарок принят.*2026-11-22/);
    // В каскад ушёл ровно ввод человека — нормализация живёт на сервере
    expect(vi.mocked(redeemGift).mock.calls[0][0]).toBe("WXYZ-2345");
    // Успех перечитал профиль: от уровня зависят гейты по всему приложению
    await waitFor(() => expect(getMyProfile).toHaveBeenCalled());
  });

  it("двойной промах говорит, что не подошло ничто", async () => {
    vi.mocked(activatePromo).mockRejectedValue(отказ(404));
    vi.mocked(redeemGift).mockRejectedValue(отказ(404, "Код недействителен"));
    const поле = await открытьВитрину();

    fireEvent.change(поле, { target: { value: "ОПЕЧАТКА" } });
    fireEvent.click(screen.getByText("Активировать"));

    await screen.findByText(/ни промокода, ни подарочного/);
    // Ввод остался в поле: человек поправит опечатку, а не набирает заново
    expect((поле as HTMLInputElement).value).toBe("ОПЕЧАТКА");
  });

  it("содержательный отказ подарка показывает текст сервера", async () => {
    vi.mocked(activatePromo).mockRejectedValue(отказ(404));
    vi.mocked(redeemGift).mockRejectedValue(
      отказ(409, "У вас уже действует уровень выше — активируйте код после окончания подписки или подарите его другому")
    );
    const поле = await открытьВитрину();

    fireEvent.change(поле, { target: { value: "AURA2345" } });
    fireEvent.click(screen.getByText("Активировать"));

    await screen.findByText(/уровень выше/);
    expect(activatePromo).toHaveBeenCalledTimes(1);
  });

  it("содержательный отказ промо не уводит ввод в подарки", async () => {
    vi.mocked(activatePromo).mockRejectedValue(отказ(410, "Промокод истёк"));
    const поле = await открытьВитрину();

    fireEvent.change(поле, { target: { value: "LETO" } });
    fireEvent.click(screen.getByText("Активировать"));

    await screen.findByText(/Промокод истёк/);
    expect(redeemGift).not.toHaveBeenCalled();
  });
});
