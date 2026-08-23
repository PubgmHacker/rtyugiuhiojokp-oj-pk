import { useCallback, useMemo, useState } from "react";
import { ChevronDown } from "lucide-react";
import { haptic } from "../lib/haptics";
import { Chip } from "./ui";
import { INTEREST_CATEGORIES } from "../lib/profileOptions";

/**
 * Выбор интересов — общий для онбординга и редактирования анкеты.
 *
 * Категории сворачиваемые: на экране 320px список из ~110 тегов одной
 * простынёй не читается. Открытые по умолчанию — те, где у человека уже есть
 * выбранный тег (правка анкеты), плюс первая категория для новых.
 */
export default function InterestsPicker({
  value,
  onChange,
  max,
}: {
  value: string[];
  onChange: (next: string[]) => void;
  max: number;
}) {
  const [openCategories, setOpenCategories] = useState<Set<string>>(() => {
    const initial = new Set<string>();
    const mine = new Set(value);
    for (const [cat, tags] of Object.entries(INTEREST_CATEGORIES)) {
      if (tags.some((t) => mine.has(t))) initial.add(cat);
    }
    if (initial.size === 0) initial.add(Object.keys(INTEREST_CATEGORIES)[0]);
    return initial;
  });

  const toggleInterest = useCallback(
    (tag: string) => {
      if (value.includes(tag)) {
        onChange(value.filter((t) => t !== tag));
        return;
      }
      if (value.length >= max) return;
      onChange([...value, tag]);
    },
    [value, onChange, max]
  );

  const toggleCategory = useCallback((cat: string) => {
    haptic("light");
    setOpenCategories((cur) => {
      const next = new Set(cur);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  }, []);

  // Теги из старой анкеты, не входящие ни в одну текущую категорию
  // (например, интерес отменили при реорганизации списка). Их нельзя молча
  // потерять при следующем сохранении — показываем отдельной секцией,
  // всегда открытой, чтобы человек видел, что выбрано, и мог снять галочку.
  const legacyInterests = useMemo(() => {
    const known = new Set(Object.values(INTEREST_CATEGORIES).flat());
    return value.filter((t) => !known.has(t));
  }, [value]);

  return (
    <div className="flex flex-col gap-2">
      {legacyInterests.length > 0 && (
        <div className="rounded-[var(--radius-tile)] border border-hairline bg-surface p-3.5">
          <p className="text-caption text-text-muted mb-2.5">
            Уже выбрано ранее
          </p>
          <div className="flex flex-wrap gap-2">
            {legacyInterests.map((tag) => (
              <Chip key={tag} active onClick={() => toggleInterest(tag)}>
                {tag}
              </Chip>
            ))}
          </div>
        </div>
      )}

      {Object.entries(INTEREST_CATEGORIES).map(([cat, tags]) => {
        const open = openCategories.has(cat);
        const chosenHere = tags.filter((t) => value.includes(t)).length;
        return (
          <div
            key={cat}
            className="rounded-[var(--radius-tile)] border border-hairline bg-surface overflow-hidden"
          >
            <button
              type="button"
              onClick={() => toggleCategory(cat)}
              aria-expanded={open}
              className="w-full flex items-center justify-between px-3.5 py-3
                         text-[14.5px] font-semibold"
            >
              <span className="flex items-center gap-2">
                {cat}
                {chosenHere > 0 && (
                  <span className="w-5 h-5 rounded-full bg-accent/15 text-accent
                                    text-[11px] font-bold flex items-center justify-center">
                    {chosenHere}
                  </span>
                )}
              </span>
              <ChevronDown
                size={17}
                className={`text-text-muted transition-transform ${open ? "rotate-180" : ""}`}
              />
            </button>
            {open && (
              <div className="flex flex-wrap gap-2 px-3.5 pb-3.5">
                {tags.map((tag) => (
                  <Chip
                    key={tag}
                    active={value.includes(tag)}
                    onClick={() => toggleInterest(tag)}
                  >
                    {tag}
                  </Chip>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
