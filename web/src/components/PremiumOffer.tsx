/**
 * Предложение Premium.
 *
 * В нативной сборке продаём через App Store: Apple запрещает вести к внешней
 * оплате из приложения (Guideline 3.1.1). В вебе и в Telegram Mini App ведём
 * в бота, где работают Stars и CryptoBot.
 *
 * Если проверка чеков на сервере не настроена, покупка не предлагается вовсе:
 * иначе оплата прошла бы, а подписка не начислилась.
 */

import { useEffect, useState } from "react";
import { Crown, ChevronRight, RotateCcw } from "lucide-react";
import { haptic } from "../lib/haptics";
import { isNative, openExternal } from "../lib/native";
import {
  isPurchaseAvailable,
  loadProducts,
  purchasePremium,
  restorePurchases,
  type IAPProduct,
} from "../lib/iap";
import { Button, Card, Spinner } from "./ui";

const BOT_USERNAME = import.meta.env.VITE_BOT_USERNAME || "souldawn_dating_bot";

interface Props {
  userId: string;
  /** Вызывается после успешной покупки — профиль нужно перечитать. */
  onPurchased: () => void;
}

export default function PremiumOffer({ userId, onPurchased }: Props) {
  const [products, setProducts] = useState<IAPProduct[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string>("");

  useEffect(() => {
    let cancelled = false;

    (async () => {
      if (!(await isPurchaseAvailable())) {
        if (!cancelled) setProducts([]);
        return;
      }
      const list = await loadProducts();
      if (!cancelled) setProducts(list);
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  // В вебе и в Telegram — прежний путь через бота
  if (!isNative()) {
    return (
      <button
        onClick={() => {
          haptic("light");
          openExternal(`https://t.me/${BOT_USERNAME}?start=premium`);
        }}
        className="w-full text-left mb-4 p-4 rounded-[var(--radius-tile)]
                   border border-accent/25 bg-accent/8 relative overflow-hidden"
      >
        <div className="flex items-center gap-3">
          <Crown size={20} className="text-accent shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="font-bold text-[15px]">Souldawn Premium</p>
            <p className="text-caption text-text-muted">
              Инкогнито и приоритет в выдаче
            </p>
          </div>
          <ChevronRight size={18} className="text-text-faint shrink-0" />
        </div>
      </button>
    );
  }

  // Пока не знаем, доступна ли покупка, — не мигаем блоком
  if (products === null) return null;

  // Покупка недоступна: показать кнопку, которая ничего не купит, нельзя
  if (products.length === 0) return null;

  const handle = async (action: () => Promise<any>, key: string) => {
    haptic("light");
    setBusy(key);
    setMessage("");
    const result = await action();
    setBusy(null);

    if (result.status === "success") {
      haptic("success");
      onPurchased();
      return;
    }
    if (result.status === "cancelled") return;
    if (result.status === "pending") {
      setMessage("Покупка ожидает подтверждения — доступ откроется автоматически");
      return;
    }
    haptic("warning");
    setMessage(result.message);
  };

  return (
    <Card className="p-4 mb-4 border-accent/25">
      <div className="flex items-center gap-2.5 mb-1.5">
        <Crown size={18} className="text-accent" />
        <span className="font-bold text-[15px] flex-1">Souldawn Premium</span>
      </div>
      <p className="text-caption text-text-muted mb-3.5">
        Инкогнито, приоритет в выдаче и 5 суперлайков в день
      </p>

      <div className="flex flex-col gap-2">
        {products.map((product) => (
          <Button
            key={product.id}
            variant="primary"
            size="md"
            fullWidth
            disabled={busy !== null}
            onClick={() => handle(() => purchasePremium(product.id, userId), product.id)}
          >
            {busy === product.id ? (
              <Spinner size={16} />
            ) : (
              <>
                {product.title || "Premium"} — {product.price}
              </>
            )}
          </Button>
        ))}

        {/* Обязательный пункт для ревью: сменивший устройство должен
            вернуть оплаченное без повторной оплаты */}
        <Button
          variant="secondary"
          size="md"
          fullWidth
          disabled={busy !== null}
          onClick={() => handle(restorePurchases, "restore")}
        >
          {busy === "restore" ? (
            <Spinner size={16} />
          ) : (
            <>
              <RotateCcw size={16} />
              Восстановить покупки
            </>
          )}
        </Button>
      </div>

      {message && (
        <p className="text-caption text-text-muted mt-3 text-center">{message}</p>
      )}
    </Card>
  );
}
