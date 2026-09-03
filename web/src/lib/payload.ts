/**
 * Проверка формы ответа на границе «сеть → состояние экрана».
 *
 * Страницы верят API на слово: `rooms.map`, `queue[0]`, `data.tiers.find`.
 * Стоит бэкенду вернуть обёртку, `null` или пустой объект — падает рендер
 * целиком, и человек видит границу ошибки «Что-то сломалось» вместо
 * родного «Не удалось загрузить» с кнопкой повтора. Хелпер превращает
 * неожиданную форму в обычное исключение, которое уже ловит catch
 * загрузчика, — экран деградирует в своё состояние ошибки, а не в аварию.
 */
export class PayloadShapeError extends TypeError {
  constructor(where: string) {
    super(`Неожиданная форма ответа: ${where}`);
    this.name = "PayloadShapeError";
  }
}

/** Возвращает `value`, если это массив, иначе бросает PayloadShapeError. */
export function assertList<T>(value: unknown, where: string): T[] {
  if (!Array.isArray(value)) throw new PayloadShapeError(where);
  return value as T[];
}
