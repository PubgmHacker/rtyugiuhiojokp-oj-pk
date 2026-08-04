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
import api from "./api";

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
  | { status: "success"; expiresAt: string }
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

/** Отправить транзакцию на сервер и подтвердить её только после успеха. */
async function redeem(tx: Transaction): Promise<string> {
  const { data } = await api.post("/iap/verify", { jws: tx.jws });
  await SouldawnIAP.finishTransaction({ transactionId: tx.transactionId });
  return data.expires_at || "";
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
    return { status: "success", expiresAt: await redeem(tx) };
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
        expiresAt = (await redeem(tx)) || expiresAt;
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
        const expiresAt = await redeem(tx);
        if (expiresAt) onPremiumChanged?.(expiresAt);
      } catch {
        // Не подтверждаем транзакцию: StoreKit принесёт её снова
      }
    });
    await SouldawnIAP.startListening();
  } catch {
    // Плагин недоступен — покупки просто не работают
  }
}
