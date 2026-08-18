/**
 * Экран заблокированного аккаунта.
 *
 * Зачем отдельный экран. `get_current_user` отдаёт 403 на каждый запрос
 * забаненного, и без этого экрана человек видел не блокировку, а сломанное
 * приложение: «не удалось загрузить анкеты» на деке, пустой список чатов,
 * молчащий профиль. Дальше он идёт в поддержку с багом, которого нет, а
 * настоящую причину узнаёт от оператора — это худший из возможных разговоров.
 *
 * Экран не делает ни одного запроса к API: любой вернулся бы тем же 403 и
 * закрутил перехватчик по кругу. Всё, что показано, берётся из локального
 * снимка аккаунта, который остался с последнего успешного входа.
 */

import { useMemo } from "react";
import { ShieldOff, ChevronRight, LogOut, Mail } from "lucide-react";
import { useStore } from "../lib/store";
import { openExternal } from "../lib/native";
import { legalUrl, SUPPORT_EMAIL, type LegalPage } from "../lib/legal";
import { haptic } from "../lib/haptics";
import { Button } from "../components/ui";

/** Локальный снимок аккаунта: сервер о себе рассказать уже не даст. */
function прочитатьСнимок(): { id?: string; display_name?: string } | null {
  try {
    const raw = localStorage.getItem("sd_user");
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return typeof parsed === "object" && parsed !== null ? parsed : null;
  } catch {
    return null;
  }
}

const ДОКУМЕНТЫ: { label: string; page: LegalPage }[] = [
  { label: "Правила сообщества", page: "guidelines" },
  { label: "Как работает модерация", page: "moderation" },
  { label: "Поддержка", page: "support" },
];

export default function Banned() {
  const logout = useStore((s) => s.logout);
  const снимок = useMemo(прочитатьСнимок, []);

  // Идентификатор в теме письма — единственное, по чему оператор находит
  // аккаунт: имени и почты у забаненного человека может не быть вовсе.
  const письмо = useMemo(() => {
    const идентификатор = снимок?.id ?? "не определён";
    const тема = encodeURIComponent(`Оспорить блокировку · ${идентификатор}`);
    const тело = encodeURIComponent(
      [
        "Здравствуйте!",
        "",
        "Прошу пересмотреть блокировку моего аккаунта.",
        `Идентификатор: ${идентификатор}`,
        снимок?.display_name ? `Имя в анкете: ${снимок.display_name}` : "",
        "",
        "Что, по моему мнению, произошло:",
        "",
      ]
        .filter(Boolean)
        .join("\n")
    );
    return `mailto:${SUPPORT_EMAIL}?subject=${тема}&body=${тело}`;
  }, [снимок]);

  return (
    <div className="min-h-screen-safe flex flex-col px-6 safe-top safe-bottom">
      <div className="flex-1 flex flex-col justify-center max-w-[420px] w-full mx-auto py-10">
        <div
          className="w-14 h-14 rounded-full bg-danger/12 border border-danger/25
                     flex items-center justify-center mb-6"
        >
          <ShieldOff size={26} className="text-danger" />
        </div>

        <h1 className="text-title font-extrabold mb-3">Доступ закрыт</h1>

        <p className="text-[15px] leading-relaxed text-text-secondary mb-2">
          Аккаунт заблокирован за нарушение правил сообщества. Анкета скрыта из
          показа, переписки и лайки недоступны.
        </p>
        <p className="text-[15px] leading-relaxed text-text-muted mb-7">
          Если считаете решение ошибочным — напишите нам. Мы разбираем такие
          обращения вручную и отвечаем каждому.
        </p>

        <Button
          size="lg"
          fullWidth
          onClick={() => {
            haptic("light");
            // openExternal, а не href: в нативной сборке origin —
            // `capacitor://localhost`, и обычная ссылка ушла бы в никуда
            openExternal(письмо);
          }}
        >
          <Mail size={17} />
          Оспорить блокировку
        </Button>

        <div className="mt-5 rounded-[var(--radius-tile)] border border-hairline overflow-hidden">
          {ДОКУМЕНТЫ.map((item, i) => (
            <button
              key={item.page}
              onClick={() => {
                haptic("light");
                openExternal(legalUrl(item.page));
              }}
              className={`w-full flex items-center gap-3 px-4 py-3.5 bg-surface
                          active:bg-surface-2 transition-colors
                          ${i > 0 ? "border-t border-hairline" : ""}`}
            >
              <span className="flex-1 text-left text-[15px]">{item.label}</span>
              <ChevronRight size={17} className="text-text-faint shrink-0" />
            </button>
          ))}
        </div>

        {снимок?.id && (
          <p className="mt-5 text-caption text-text-faint break-all">
            Аккаунт: {снимок.id}
          </p>
        )}
      </div>

      {/* Выход нужен не для того, чтобы «попробовать ещё раз», а чтобы отдать
          устройство другому человеку: без него телефон остаётся запертым на
          заблокированном аккаунте. */}
      <button
        onClick={() => {
          haptic("light");
          logout();
          window.location.href = "/login";
        }}
        className="mx-auto mb-4 flex items-center gap-2 py-3 px-4
                   text-[14px] font-medium text-text-muted tap-target"
      >
        <LogOut size={16} />
        Выйти из аккаунта
      </button>
    </div>
  );
}
