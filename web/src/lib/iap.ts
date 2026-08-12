/**
 * Покупка Premium через StoreKit 2 в нативной сборке iOS.
 *
 * Apple требует, чтобы разблокировка функций внутри приложения продавалась
 * только через App Store (Guideline 3.1.1). В вебе и в Telegram Mini App
 * покупка идёт через бота, поэтому здесь всё под проверкой isNative().
 *
 * Порядок важен: транзакция подтверждается только после того, как сервер
 * её зачёл. Если подтвердить раньше и запрос не дойдёт, деньги списаны, а
 * доступа нет — повторно получить ту же транзакцию уже нельзя.
 */

import { registerPlugin } from "@capacitor/core";
import { isNative } from "./native";
import api, { type IAPVerifyResponse } from "./api";

export interface IAPProduct {
  id: string;
  title: string;
  description: string;
  /** Цена, уже отформатированная под регион пользователя. */
  price: string;
  priceValue: number;
  currency: string;
}

interface Transaction {
  transactionId: string;
  productId: string;
  jws: string;
}

interface IAPPlugin {
  isAvailable(): Promise<{ available: boolean }>;
  getProducts(options: { productIds: string[] }): Promise<{ products: IAPProduct[] }>;
  purchase(options: { productId: string; appAccountToken?: string }): Promise<Transaction>;
  finishTransaction(options: { transactionId: string }): Promise<void>;
  getCurrentEntitlements(options: { force: boolean }): Promise<{ entitlements: Transaction[] }>;
  startListening(): Promise<void>;
  addListener(
    event: "transactionUpdate",
    handler: (tx: Transaction) => void
  ): Promise<{ remove: () => Promise<void> }>;
}

const SouldawnIAP = registerPlugin<IAPPlugin>("SouldawnIAP");

export type PurchaseOutcome =
  | { status: "success"; expiresAt: string; giftCode?: string }
  | { status: "cancelled" }
  /** Ask to Buy: решение придёт позже, начислим при следующем запуске. */
  | { status: "pending" }
  | { status: "error"; message: string };

/** Какие продукты продаёт сервер. Пустой список — покупка недоступна. */
async function serverProductIds(): Promise<string[]> {
  const { data } = await api.get("/iap/products");
  return data.available ? data.product_ids : [];
}

/**
 * Доступна ли покупка внутри приложения. Проверяем и платформу, и сервер:
 * без ключей проверки чеков кнопку показывать нельзя — оплата прошла бы,
 * а подписка не начислилась.
 */
export async function isPurchaseAvailable(): Promise<boolean> {
  if (!isNative()) return false;
  try {
    const [{ available }, ids] = await Promise.all([
      SouldawnIAP.isAvailable(),
      serverProductIds(),
    ]);
    return available && ids.length > 0;
  } catch {
    return false;
  }
}

/** Товары с ценами из App Store — цену показываем ту, что назовёт Apple. */
export async function loadProducts(): Promise<IAPProduct[]> {
  if (!isNative()) return [];
  try {
    const productIds = await serverProductIds();
    if (!productIds.length) return [];
    const { products } = await SouldawnIAP.getProducts({ productIds });
    return products.sort((a, b) => a.priceValue - b.priceValue);
  } catch {
    return [];
  }
}

/** Отправить транзакцию на сервер и подтвердить её только после успеха.
 *
 * `kind` решает, чем станет платёж: подпиской покупателю или подарочным
 * кодом. Раньше ручка была одна, а признак подарка ехал полем, которое
 * сервер не читал — деньги списывались, подписка доставалась покупателю,
 * а подарок не рождался.
 */
async function redeem(
  tx: Transaction,
  kind: "self" | "gift" = "self",
): Promise<{ expiresAt: string; giftCode?: string; alreadyProcessed: boolean }> {
  const data: IAPVerifyResponse =
    kind === "gift"
      ? (await api.post("/iap/verify-gift", { jws: tx.jws })).data
      : (await api.post("/iap/verify", { jws: tx.jws })).data;
  // Подтверждаем чек именем Apple, как в документации: иначе сервер
  // не подпишет ту же транзакцию, и мы спишем деньги без начисления
  await SouldawnIAP.finishTransaction({ transactionId: tx.transactionId });
  return {
    expiresAt: data.expires_at || "",
    giftCode: data.gift_code || undefined,
    alreadyProcessed: Boolean(data.already_processed),
  };
}

/**
 * Купить подписку.
 *
 * `appAccountToken` — id пользователя: сервер сверяет его с тем, кто
 * предъявляет чек, иначе валидный чужой чек можно приклеить к любому аккаунту.
 */
export async function purchasePremium(
  productId: string,
  userId: string
): Promise<PurchaseOutcome> {
  if (!isNative()) {
    return { status: "error", message: "Покупка доступна только в приложении" };
  }

  try {
    const tx = await SouldawnIAP.purchase({ productId, appAccountToken: userId });
    const { expiresAt, giftCode } = await redeem(tx);
    return { status: "success", expiresAt, giftCode };
  } catch (e: any) {
    const code = e?.code || e?.message || "";
    if (code === "cancelled") return { status: "cancelled" };
    if (code === "pending") return { status: "pending" };
    return {
      status: "error",
      message: e?.response?.data?.detail || e?.message || "Не удалось завершить покупку",
    };
  }
}

/**
 * Восстановление покупок — обязательный пункт для ревью App Store: человек,
 * сменивший устройство, должен вернуть оплаченное без повторной оплаты.
 */
export async function restorePurchases(): Promise<PurchaseOutcome> {
  if (!isNative()) {
    return { status: "error", message: "Доступно только в приложении" };
  }

  try {
    const { entitlements } = await SouldawnIAP.getCurrentEntitlements({ force: true });
    if (!entitlements.length) {
      return { status: "error", message: "Активных покупок не найдено" };
    }

    let expiresAt = "";
    for (const tx of entitlements) {
      try {
        const result = await redeem(tx);
        if (result.expiresAt) expiresAt = result.expiresAt;
      } catch {
        // Одна неудачная транзакция не должна ронять восстановление остальных
      }
    }

    return expiresAt
      ? { status: "success", expiresAt }
      : { status: "error", message: "Не удалось восстановить покупки" };
  } catch (e: any) {
    return { status: "error", message: e?.message || "Не удалось восстановить покупки" };
  }
}

/**
 * Слушатель транзакций, приходящих вне покупки: автопродления, покупка с
 * другого устройства, отложенные подтверждения. Без него продление подписки
 * сервер не увидит, и Premium погаснет у платящего пользователя.
 */
export async function startTransactionListener(
  onPremiumChanged?: (expiresAt: string) => void
): Promise<void> {
  if (!isNative()) return;
  try {
    await SouldawnIAP.addListener("transactionUpdate", async (tx) => {
      try {
        const result = await redeem(tx);
        if (result.expiresAt) onPremiumChanged?.(result.expiresAt);
      } catch {
        // Не подтверждаем транзакцию: StoreKit принесёт её снова
      }
    })
    await SouldawnIAP.startListening();
  } catch {
    // Плагин недоступен — покупки просто не работают
  }
}

/**
 * Купить Premium в подарок.
 *
 * Сервер не начисляет подписку никому, а выдаёт одноразовый код —
 * получателя выбирает покупатель, пересылая код куда угодно. Так подарок
 * работает и для того, кто ещё не зарегистрирован, и не требует знать
 * чужой user_id до оплаты.
 *
 * Код возвращается один раз. Если ответ потерян по сети, повторная
 * проверка того же чека придёт с already_processed и без кода: второй
 * подарок за те же деньги сервер не выпишет.
 */
export async function purchaseGift(
  productId: string,
  userId: string,
): Promise<PurchaseOutcome> {
  if (!isNative()) {
    return { status: "error", message: "Доступно только в приложении" };
  }
  try {
    const tx = await SouldawnIAP.purchase({ productId, appAccountToken: userId });
    const { expiresAt, giftCode, alreadyProcessed } = await redeem(tx, "gift");
    if (alreadyProcessed && !giftCode) {
      return {
        status: "error",
        message: "Подарок за эту покупку уже оформлен — код был показан ранее",
      };
    }
    return { status: "success", expiresAt, giftCode };
  } catch (e: any) {
    const code = e?.code || e?.message || "";
    if (code === "cancelled") return { status: "cancelled" };
    if (code === "pending") return { status: "pending" };
    return {
      status: "error",
      message: e?.response?.data?.detail || e?.message || "Не удалось оформить подарок",
    };
  }
}
