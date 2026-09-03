import { useEffect, useState, useCallback } from "react";
import { Calendar, Flame, UserCheck, Users, TrendingDown } from "lucide-react";
import { getAdminMetrics, type AdminMetrics } from "../../lib/admin";
import { Button, EmptyState, Skeleton } from "../ui";

/**
 * Метрики продукта: активность (DAU/WAU/MAU), недельный retention и выручка.
 *
 * Активность — вход в мини-апп; retention — «вернулся спустя N дней или
 * позже», незакрытые окна показываются прочерком, а не заниженной долей.
 * Суммы приходят в минорных единицах валют — здесь они переводятся в
 * человеческие (копейки → рубли, сотые → USDT, звёзды остаются звёздами).
 */

const ВАЛЮТЫ: Record<string, string> = {
  XTR: "Telegram Stars",
  RUB: "Рубли — СБП",
  USDT: "USDT — CryptoBot",
};

const сумма = (currency: string, amount: number): string => {
  if (currency === "XTR") return `${amount.toLocaleString("ru")} Stars`;
  if (currency === "RUB") return `${(amount / 100).toLocaleString("ru")} ₽`;
  if (currency === "USDT") return `${(amount / 100).toLocaleString("ru")} USDT`;
  return `${amount.toLocaleString("ru")} ${currency}`;
};

const доля = (d: number | null): string =>
  d === null ? "—" : `${Math.round(d * 100)}%`;

/** «18.08 – 24.08» из понедельника ISO-недели. */
const неделя = (week: string): string => {
  const от = new Date(week + "T00:00:00");
  const до = new Date(от);
  до.setDate(до.getDate() + 6);
  const ф = (d: Date) =>
    d.toLocaleDateString("ru", { day: "2-digit", month: "2-digit" });
  return `${ф(от)} – ${ф(до)}`;
};

export default function MetricsPanel() {
  const [метрики, setМетрики] = useState<AdminMetrics | null>(null);
  const [сбой, setСбой] = useState(false);

  const загрузить = useCallback(() => {
    setСбой(false);
    setМетрики(null);
    getAdminMetrics()
      .then(setМетрики)
      .catch(() => setСбой(true));
  }, []);

  useEffect(загрузить, [загрузить]);

  if (сбой) {
    return (
      <EmptyState
        icon={TrendingDown}
        title="Не удалось загрузить"
        description="Проверьте соединение и попробуйте снова."
        action={
          <Button variant="secondary" size="md" onClick={загрузить}>
            Повторить
          </Button>
        }
      />
    );
  }

  if (!метрики) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-28 rounded-2xl" />
          ))}
        </div>
        <Skeleton className="h-64 rounded-[var(--radius-tile)]" />
      </div>
    );
  }

  const карточки = [
    { label: "DAU", value: метрики.dau, icon: UserCheck, color: "text-success", sub: "заходили за сутки" },
    { label: "WAU", value: метрики.wau, icon: Users, color: "text-info", sub: "за 7 дней" },
    { label: "MAU", value: метрики.mau, icon: Calendar, color: "text-accent", sub: "за 30 дней" },
    { label: "Stickiness", value: `${Math.round(метрики.stickiness * 100)}%`, icon: Flame, color: "text-warn", sub: "DAU / MAU" },
  ];

  // Свежие когорты сверху — как во всех списках админки
  const когорты = [...метрики.cohorts].reverse();

  return (
    <div className="space-y-6">
      {/* Активность */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {карточки.map((к) => (
          <div key={к.label} className="bg-surface rounded-2xl p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-text-muted">{к.label}</span>
              <к.icon size={18} className={к.color} />
            </div>
            <p className="text-2xl font-bold mb-1">
              {typeof к.value === "number" ? к.value.toLocaleString("ru") : к.value}
            </p>
            <p className="text-xs text-text-muted">{к.sub}</p>
          </div>
        ))}
      </div>

      {/* Retention */}
      <div className="rounded-[var(--radius-tile)] bg-surface border border-hairline">
        <div className="px-4 pt-4">
          <h3 className="text-sm font-semibold">Возвращаемость по неделям</h3>
          <p className="mt-1 text-xs text-text-muted">
            Доля вернувшихся спустя 1 / 7 / 30 дней и позже, по неделе
            регистрации. «—» — окно ещё не закрыто: последние из когорты не
            прожили свои N дней.
          </p>
        </div>
        <div className="overflow-x-auto mt-2">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-text-muted text-xs uppercase tracking-wider">
                <th className="px-4 py-3">Неделя</th>
                <th className="px-4 py-3">Новых</th>
                <th className="px-4 py-3">D1</th>
                <th className="px-4 py-3">D7</th>
                <th className="px-4 py-3">D30</th>
              </tr>
            </thead>
            <tbody>
              {когорты.map((к) => (
                <tr key={к.week} className="border-t border-white/5">
                  <td className="px-4 py-3 whitespace-nowrap">{неделя(к.week)}</td>
                  <td className="px-4 py-3">{к.size.toLocaleString("ru")}</td>
                  <td className="px-4 py-3">{доля(к.d1)}</td>
                  <td className="px-4 py-3">{доля(к.d7)}</td>
                  <td className="px-4 py-3">{доля(к.d30)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Выручка */}
      <div className="rounded-[var(--radius-tile)] bg-surface border border-hairline">
        <div className="px-4 pt-4">
          <h3 className="text-sm font-semibold">Выручка</h3>
          <p className="mt-1 text-xs text-text-muted">
            {метрики.revenue_since
              ? `Суммы платежей записываются с ${new Date(
                  метрики.revenue_since
                ).toLocaleDateString("ru")} — то, что раньше, в выручке не видно.`
              : "Платежей с суммами ещё не было."}{" "}
            Покупки в App Store сюда не входят — их выручку считает App Store
            Connect.
          </p>
        </div>
        {метрики.revenue.length === 0 ? (
          <p className="px-4 py-6 text-sm text-text-muted">
            Как только пройдёт первый платёж, здесь появятся суммы по валютам.
          </p>
        ) : (
          <div className="overflow-x-auto mt-2">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-text-muted text-xs uppercase tracking-wider">
                  <th className="px-4 py-3">Валюта</th>
                  <th className="px-4 py-3">За 30 дней</th>
                  <th className="px-4 py-3">За всё время</th>
                  <th className="px-4 py-3">Платящих</th>
                </tr>
              </thead>
              <tbody>
                {метрики.revenue.map((р) => (
                  <tr key={р.currency} className="border-t border-white/5">
                    <td className="px-4 py-3 whitespace-nowrap">
                      {ВАЛЮТЫ[р.currency] ?? р.currency}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className="font-semibold">
                        {сумма(р.currency, р.amount_30d)}
                      </span>
                      <span className="text-text-muted"> · {р.count_30d} пл.</span>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className="font-semibold">
                        {сумма(р.currency, р.amount_total)}
                      </span>
                      <span className="text-text-muted"> · {р.count_total} пл.</span>
                    </td>
                    <td className="px-4 py-3">{р.payers_total.toLocaleString("ru")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
