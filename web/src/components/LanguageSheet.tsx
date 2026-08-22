/**
 * Выбор языка интерфейса.
 *
 * Язык человек выбирает в боте первым экраном, но менять его там нечем: команды
 * смены языка у бота нет, а переустанавливать /start ради флага никто не будет.
 * Здесь — единственное место, где выбор правится.
 *
 * Применяем сразу по нажатию, до ответа сервера, как и схему оформления: язык
 * меняет весь интерфейс, и ждать сеть, глядя на непонятный текст, — ровно та
 * ситуация, из которой человек сюда пришёл. Сервер догоняет, при отказе
 * откатываем и говорим об этом прямо: молчаливый откат человек прочтёт как
 * «приложение сломано».
 */
import { useState } from "react";
import { Check } from "lucide-react";
import { Sheet } from "./Sheet";
import { useStore } from "../lib/store";
import { haptic } from "../lib/haptics";
import { updateMyProfile } from "../lib/api";
import { ЯЗЫКИ, НАЗВАНИЯ, useT, useЯзык, нормализовать, type Язык } from "../lib/i18n";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function LanguageSheet({ open, onClose }: Props) {
  const user = useStore((s) => s.user);
  const setUser = useStore((s) => s.setUser);
  const язык = useЯзык();
  const t = useT();
  const [ошибка, setОшибка] = useState(false);
  const [сохранён, setСохранён] = useState(false);

  const выбрать = async (код: Язык) => {
    if (!user || код === язык) return;
    haptic("light");
    setОшибка(false);
    setСохранён(false);

    const прежний = user.locale;
    // Локальная правка одного поля, а не подмена профиля ответом: ответ на
    // PATCH несёт не все колонки аккаунта, и целиком он затёр бы соседние.
    setUser({ ...user, locale: код });

    try {
      const ответ = await updateMyProfile({ locale: код });
      // Сервер — источник истины: он мог нормализовать код иначе, чем мы.
      setUser({ ...user, locale: нормализовать(ответ.locale ?? код) });
      setСохранён(true);
    } catch {
      setUser({ ...user, locale: прежний });
      setОшибка(true);
    }
  };

  return (
    <Sheet open={open} onClose={onClose} title={t("lang.title")} subtitle={t("lang.hint")}>
      {ошибка && (
        <div className="mb-3 rounded-[10px] border border-danger/30 bg-danger/10 px-3 py-2 text-[13px] text-danger">
          {t("lang.failed")}
        </div>
      )}
      {сохранён && !ошибка && (
        <div className="mb-3 rounded-[10px] border border-success/30 bg-success/10 px-3 py-2 text-[13px] text-success">
          {t("lang.saved")}
        </div>
      )}

      <div className="flex flex-col gap-1.5 pb-2">
        {ЯЗЫКИ.map((код) => {
          const выбран = код === язык;
          return (
            <button
              key={код}
              type="button"
              onClick={() => выбрать(код)}
              aria-current={выбран ? "true" : undefined}
              // lang на кнопке: читалка обязана произнести «Türkçe» по-турецки,
              // иначе название языка звучит неузнаваемо для того, кто его ищет
              lang={код}
              className={`flex items-center justify-between rounded-[12px] border px-3.5 py-3 text-left text-[15px] transition-colors ${
                выбран
                  ? "border-accent bg-accent/12 text-text"
                  : "border-hairline bg-surface-2 text-text"
              }`}
            >
              <span>{НАЗВАНИЯ[код]}</span>
              {выбран && <Check size={17} className="shrink-0 text-accent" />}
            </button>
          );
        })}
      </div>

      {/* Сказано прямо: часть экранов ещё по-русски. Человек, выбравший
          турецкий и увидевший русский текст, иначе решит, что выбор не сработал,
          и будет жать снова. */}
      <p className="pb-3 text-[12px] leading-snug text-text-muted">{t("lang.partial")}</p>
    </Sheet>
  );
}
