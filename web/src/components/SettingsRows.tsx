/**
 * Стек настроек в идиоме iOS-клиента Plink (SettingsScaffold/SettingsCard).
 *
 * Группа = подпись капителью над стеклянной картой r20. Внутри — строки с
 * круглым значком, заголовком, подсказкой или значением справа и шевроном.
 * Разделители рисует сама строка (CSS `settings-row`, от отметки 60 под
 * значком) и только между соседями: у первой строки линии нет. Своих
 * подложек у строк нет — стекло даёт карта, иначе получится «карточка в
 * карточке», от чего Plink как раз ушёл. Карта — `settings-card`, а не
 * `glass`: без верхней подсветки, которая на длинном списке выглядела как
 * выделенная первая строка.
 *
 * Строка бывает ссылкой (`to`) или кнопкой (`onClick`). Ничего другого
 * компонент не знает: содержимое подэкранов — забота маршрутов.
 */
import type { ComponentType, ReactNode } from "react";
import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import { haptic } from "../lib/haptics";

export function SettingsGroup({
  title,
  children,
  className = "",
}: {
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={className}>
      {title && <h2 className="settings-label mb-2 px-[14px]">{title}</h2>}
      <div className="settings-card rounded-[20px] py-1">{children}</div>
    </section>
  );
}

export interface SettingsRowProps {
  icon: ComponentType<{ size?: number; className?: string; style?: React.CSSProperties }>;
  title: ReactNode;
  hint?: ReactNode;
  /** Значение справа: название языка, точки палитры и т. п. */
  value?: ReactNode;
  /** Язык значения для читалки, если оно на другом языке («Türkçe»). */
  valueLang?: string;
  to?: string;
  onClick?: () => void;
  /** Нужна подписка: словесный значок «Plus» у заголовка. Один признак на
      одно значение и с именем для читалки — два молчаливых значка (звезда
      плюс замок) значили то же самое и не назывались вслух. */
  plus?: boolean;
  /** Шеврон справа; у строк-переключателей он не нужен. */
  chevron?: boolean;
  /** Цвет значка вместо акцента (например, синий галочки). */
  iconColor?: string;
  /** Опасное действие (удалить аккаунт): заголовок и значок — красным. */
  tone?: "danger";
  disabled?: boolean;
  ariaLabel?: string;
}

export function SettingsRow({
  icon: Icon,
  title,
  hint,
  value,
  valueLang,
  to,
  onClick,
  plus,
  chevron = true,
  iconColor,
  tone,
  disabled,
  ariaLabel,
}: SettingsRowProps) {
  const цвет = iconColor ?? (tone === "danger" ? "var(--color-danger)" : undefined);
  const тап = () => {
    if (disabled) return;
    haptic(tone === "danger" ? "warning" : "light");
    onClick?.();
  };
  const тело = (
    <>
      <span
        className="settings-badge"
        style={
          цвет
            ? {
                color: цвет,
                background: `color-mix(in srgb, ${цвет} 14%, transparent)`,
                boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${цвет} 22%, transparent)`,
              }
            : undefined
        }
      >
        <Icon size={15} />
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <p
            className={`font-semibold text-[15px] leading-tight truncate ${
              tone === "danger" ? "text-danger" : ""
            }`}
          >
            {title}
          </p>
          {plus && (
            <span className="plus-badge shrink-0">
              Plus<span className="sr-only"> — нужна подписка</span>
            </span>
          )}
        </div>
        {hint && (
          <p className="text-[12px] text-text-muted mt-0.5 leading-snug">{hint}</p>
        )}
      </div>
      {value !== undefined && (
        <span
          className="flex items-center gap-2 text-[14px] text-text-muted shrink-0"
          lang={valueLang}
        >
          {value}
        </span>
      )}
      {chevron && <ChevronRight size={14} className="text-text-faint shrink-0" />}
    </>
  );
  if (to) {
    return (
      <Link to={to} onClick={тап} className="settings-row" aria-label={ariaLabel}>
        {тело}
      </Link>
    );
  }
  return (
    <button
      type="button"
      onClick={тап}
      disabled={disabled}
      className="settings-row disabled:opacity-60"
      aria-label={ariaLabel}
    >
      {тело}
    </button>
  );
}
