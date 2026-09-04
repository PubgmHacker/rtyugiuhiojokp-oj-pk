import type { UserProfile } from "./api";

/**
 * Заполненность анкеты — одна таблица на всё приложение.
 *
 * Жила внутри Profile.tsx. Экран редактирования показывает ту же полосу над
 * формой, и вторая копия весов разъехалась бы с первой на первом же новом
 * поле: человек видел бы 85 % в профиле и 92 % в редакторе и не понимал бы,
 * какой цифре верить.
 *
 * Веса не равные: без фото и имени анкету не показывают вовсе, а MBTI —
 * приятное дополнение. Сумма ровно 100, иначе «100 %» не достигалось бы
 * никогда.
 *
 * `key` совпадает с id секции редактора (`edit-<key>`) и с ключом ?focus= —
 * по нему полоса умеет прокрутить прямо к незаполненному полю.
 */
export interface ПунктАнкеты {
  key: string;
  label: string;
  weight: number;
  done: (p: UserProfile) => boolean;
}

export const COMPLETENESS: ПунктАнкеты[] = [
  { key: "name", label: "Имя", weight: 10, done: (p) => !!p.display_name },
  { key: "photos", label: "Хотя бы одно фото", weight: 20, done: (p) => !!p.photos?.length },
  {
    key: "photos",
    // Метка попадает в строку «Осталось: …» в нижнем регистре — форма
    // «минимум три фото» читается там как продолжение фразы
    label: "Минимум три фото",
    weight: 15,
    done: (p) => (p.photos?.length ?? 0) >= 3,
  },
  { key: "bio", label: "Пара слов о себе", weight: 15, done: (p) => !!p.bio },
  { key: "interests", label: "Интересы", weight: 10, done: (p) => !!p.interests?.length },
  { key: "city", label: "Город", weight: 10, done: (p) => !!p.city },
  { key: "goal", label: "Цель знакомства", weight: 10, done: (p) => !!p.goal },
  { key: "subculture", label: "Субкультура", weight: 5, done: (p) => !!p.subculture },
  { key: "height", label: "Рост", weight: 3, done: (p) => p.height_cm != null },
  { key: "mbti", label: "Тип личности", weight: 2, done: (p) => !!p.mbti },
];

/** Процент и то, чего не хватает, — в порядке убывания веса пункта. */
export function заполненность(p: UserProfile): {
  percent: number;
  missing: ПунктАнкеты[];
} {
  const missing = COMPLETENESS.filter((item) => !item.done(p));
  const percent = COMPLETENESS.filter((item) => item.done(p)).reduce(
    (sum, item) => sum + item.weight,
    0
  );
  return { percent, missing };
}
