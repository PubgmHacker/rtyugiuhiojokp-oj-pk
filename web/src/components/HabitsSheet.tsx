/**
 * План дня поверх переписки.
 *
 * Смысл именно в том, что панель открывается из чата: человек ведёт день
 * не выходя из диалога, и приложение перестаёт быть только про свидания.
 * Тот же список показывает экран /habits — общий хук, два входа.
 */
import { Sheet } from "./Sheet";
import { HabitList } from "./HabitList";

export function HabitsSheet({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="План на день"
      subtitle="Отметки сбрасываются в полночь"
    >
      <div className="pb-2">
        <HabitList compact />
      </div>
    </Sheet>
  );
}
