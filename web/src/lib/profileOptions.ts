/**
 * Нишевые поля анкеты: цель знакомства и субкультура.
 *
 * Список один для анкеты и для фильтра — иначе выбранное в анкете значение
 * невозможно было бы найти фильтром. Значения латиницей: они уходят в базу и
 * не должны зависеть от того, как мы завтра перепишем подпись.
 */

export interface Option {
  value: string;
  label: string;
}

export const GOALS: Option[] = [
  { value: "relationship", label: "Отношения" },
  { value: "friendship", label: "Дружба" },
  { value: "chat", label: "Общение" },
  { value: "dates", label: "Свидания" },
];

export const SUBCULTURES: Option[] = [
  { value: "alt", label: "Альт" },
  { value: "anime", label: "Аниме" },
  { value: "goth", label: "Гот" },
  { value: "grunge", label: "Гранж" },
  { value: "kpop", label: "K-pop" },
  { value: "metal", label: "Металл" },
  { value: "punk", label: "Панк" },
  { value: "rap", label: "Рэп" },
  { value: "skate", label: "Скейт" },
  { value: "gamer", label: "Гейминг" },
  { value: "casual", label: "Кэжуал" },
  { value: "emo", label: "Эмо" },
];

/** Подпись по значению; неизвестное значение показываем как есть. */
export function optionLabel(options: Option[], value: string): string {
  return options.find((o) => o.value === value)?.label ?? value;
}

export const HEIGHT_MIN = 140;
export const HEIGHT_MAX = 210;

/**
 * Причины жалобы. Набор обязан совпадать с REPORT_REASONS в
 * api/models/schemas.py и с кнопками бота: жалоба с неизвестной причиной не
 * пройдёт валидацию API и останется без подписи в админке.
 */
export const REPORT_REASONS: Option[] = [
  { value: "spam", label: "Спам или реклама" },
  { value: "harassment", label: "Оскорбления" },
  { value: "nudity", label: "Нагота" },
  { value: "scam", label: "Мошенничество" },
  { value: "fake", label: "Чужие фото" },
  { value: "drugs", label: "Наркотики" },
  { value: "underage", label: "Похоже, ребёнок" },
  { value: "other", label: "Другое" },
];
