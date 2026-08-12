/**
 * План дня — отдельный экран.
 *
 * Тот же список, что в панели чата, но с местом под смысл раздела:
 * из панели человек отмечает, с экрана — планирует. Разделять данные
 * между ними нельзя, поэтому разделён только контекст.
 */
import { useNavigate } from "react-router-dom";
import { ChevronLeft, Flame } from "lucide-react";
import { ScreenHeader } from "../components/ui";
import { HabitList } from "../components/HabitList";
import { haptic } from "../lib/haptics";
import { useSectionOpen } from "../lib/useSectionOpen";

export default function Habits() {
  const navigate = useNavigate();

  // Открытие раздела — единственный сигнал, по которому видно, живёт ли
  // фича. Хук отправляет один раз за монтирование и глушит ошибку сам.
  useSectionOpen("habits");

  return (
    <div className="min-h-screen-safe bg-bg pb-nav">
      <ScreenHeader
        title="План дня"
        subtitle="Отметки сбрасываются в полночь"
        left={
          <button
            onClick={() => {
              haptic("light");
              navigate(-1);
            }}
            aria-label="Назад"
            className="tap-target grid h-9 w-9 place-items-center rounded-full text-text-muted transition-colors active:bg-surface-2"
          >
            <ChevronLeft size={22} />
          </button>
        }
      />

      <div className="px-4 pt-3">
        <HabitList />

        <div className="mt-6 flex items-start gap-3 rounded-[14px] border border-hairline bg-surface px-4 py-3.5">
          <Flame size={18} className="mt-0.5 shrink-0 text-accent" />
          <p className="text-[13px] leading-relaxed text-text-muted">
            План открывается прямо из переписки — значок со списком в шапке
            чата. Планировать день, не выходя из диалога.
          </p>
        </div>
      </div>
    </div>
  );
}
