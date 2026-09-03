import { useEffect, useState } from "react";
import { BadgeCheck, ShieldCheck, Bell } from "lucide-react";
import {
  getNotifications,
  markNotificationsRead,
  type NotificationItem,
  type NotificationsPage,
} from "../lib/api";
import { useStore } from "../lib/store";
import { EmptyState, LoadError, ScreenHeader, Skeleton } from "../components/ui";

/** Центр уведомлений: события, у которых нет своего экрана с бейджем.
 *
 *  Тексты собираются здесь, а не на сервере: API отдаёт kind+payload и не
 *  знает языка интерфейса (та же доктрина, что у пушей report_notify.py).
 *  Тексты итогов жалоб дословно зеркалят эти пуши — пуш и карточка в ленте
 *  описывают одно событие, расходиться им нельзя. */

const ИТОГИ_ЖАЛОБ: Record<string, { заголовок: string; текст: string }> = {
  "hidden": {
    заголовок: "Жалоба сработала",
    текст: "Анкета скрыта из поиска — её проверит модератор.",
  },
  "banned": {
    заголовок: "Жалоба подтверждена",
    текст: "Аккаунт заблокирован. Больше он вам не встретится.",
  },
  "resolved": {
    заголовок: "Жалоба рассмотрена",
    текст: "Модератор проверил анкету и принял меры.",
  },
  "dismissed": {
    заголовок: "Жалоба рассмотрена",
    текст:
      "Модератор не нашёл нарушения правил. Мешающего человека можно " +
      "заблокировать в его анкете.",
  },
};

function содержимое(
  n: NotificationItem
): { Икона: typeof ShieldCheck; заголовок: string; текст: string } | null {
  if (n.kind === "verification_approved") {
    return {
      Икона: BadgeCheck,
      заголовок: "Профиль подтверждён",
      текст: "Галочка уже в анкете: люди видят, что фото настоящие.",
    };
  }
  if (n.kind === "report_outcome") {
    const итог = ИТОГИ_ЖАЛОБ[n.payload.outcome ?? ""];
    return итог ? { Икона: ShieldCheck, ...итог } : null;
  }
  // Незнакомый вид — событие из более новой версии API: молча прячем,
  // карточка с «undefined» хуже отсутствия карточки
  return null;
}

function когда(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", {
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function Notifications() {
  const setUnreadNotifications = useStore((s) => s.setUnreadNotifications);
  const [страница, setСтраница] = useState<NotificationsPage | null>(null);
  const [сбой, setСбой] = useState(false);
  const [попытка, setПопытка] = useState(0);

  useEffect(() => {
    let жив = true;
    setСбой(false);
    setСтраница(null);
    getNotifications()
      .then((данные) => {
        if (!жив) return;
        setСтраница(данные);
        if (данные.unread > 0) {
          // Точка на колокольчике гаснет сразу, сервер догоняет фоном:
          // упавший POST не страшен — следующий /badges вернёт правду.
          // Локальные read_at не трогаем: подсветка «что нового» живёт
          // до конца этого показа
          setUnreadNotifications(0);
          markNotificationsRead().catch(() => {});
        }
      })
      .catch(() => жив && setСбой(true));
    return () => {
      жив = false;
    };
  }, [попытка, setUnreadNotifications]);

  // Незнакомые виды спрятаны до ветвления: лента из одних незнакомых
  // событий — это «Пока тихо», а не список пустых карточек
  const видимые = (страница?.items ?? []).filter((n) => содержимое(n) !== null);

  return (
    <div className="max-w-[520px] mx-auto w-full flex flex-col min-h-[calc(100dvh-68px)]">
      <ScreenHeader title="Уведомления" />

      {сбой ? (
        <LoadError onRetry={() => setПопытка((x) => x + 1)} />
      ) : страница === null ? (
        <div className="px-4 pt-3 space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-[86px]" />
          ))}
        </div>
      ) : видимые.length === 0 ? (
        <EmptyState
          icon={Bell}
          title="Пока тихо"
          description="Здесь появятся итоги ваших жалоб и другие события — всё важное, у чего нет своей вкладки."
        />
      ) : (
        <ul className="px-4 pt-3 pb-6 space-y-2">
          {видимые.map((n) => {
            const { Икона, заголовок, текст } = содержимое(n)!;
            return (
              <li
                key={n.id}
                className="flex items-start gap-3 p-4 bg-surface-2 border
                           border-hairline rounded-[var(--radius-tile)]"
              >
                <span
                  aria-hidden
                  className="shrink-0 w-9 h-9 rounded-full bg-accent/10
                             text-accent flex items-center justify-center"
                >
                  <Икона size={18} />
                </span>
                <div className="flex-1 min-w-0">
                  <p className="font-semibold text-[15px] leading-tight">
                    {заголовок}
                  </p>
                  <p className="text-[13.5px] text-text-muted leading-snug mt-1">
                    {текст}
                  </p>
                  <p className="text-[12px] text-text-faint mt-1.5">
                    {когда(n.created_at)}
                  </p>
                </div>
                {!n.read_at && (
                  <span
                    aria-label="Новое"
                    className="shrink-0 mt-1.5 w-2 h-2 rounded-full bg-accent"
                  />
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
