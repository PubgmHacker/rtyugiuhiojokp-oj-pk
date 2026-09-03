import { useEffect, useState, useCallback } from "react";
import { EyeOff, Eye, WifiOff, Camera } from "lucide-react";
import { getAdminStories, moderateStory, type AdminStory } from "../../lib/admin";
import { Button, EmptyState, Skeleton } from "../ui";

/**
 * Очередь историй для ручной проверки.
 *
 * Автоматика двойная — AI на загрузке и снятие по двум жалобам, — но история
 * живёт сутки, и жалобы от аудитории «пары» может не собрать вовсе. Этот
 * экран закрывает щель, пока кадр ещё показывается.
 *
 * Историю не удаляем, а прячем: жалоба могла быть ложной, а удалённый кадр
 * нечем показать поддержке, когда автор придёт спорить.
 */

const АУДИТОРИЯ: Record<string, string> = {
  matches: "видят пары",
  everyone: "видят все",
};

export default function StoriesTable() {
  const [stories, setStories] = useState<AdminStory[] | null>(null);
  const [сбой, setСбой] = useState(false);
  const [занят, setЗанят] = useState<string | null>(null);
  const [толькоВидимые, setТолькоВидимые] = useState(false);

  const загрузить = useCallback(() => {
    setСбой(false);
    setStories(null);
    getAdminStories(толькоВидимые)
      .then(setStories)
      .catch(() => setСбой(true));
  }, [толькоВидимые]);

  useEffect(загрузить, [загрузить]);

  const действие = async (s: AdminStory) => {
    setЗанят(s.id);
    try {
      await moderateStory(s.id, s.is_hidden ? "show" : "hide");
      // Обновляем на месте: перезагрузка списка сбрасывает прокрутку, а
      // модератор идёт по очереди сверху вниз
      setStories((прежние) =>
        (прежние ?? []).map((x) =>
          x.id === s.id ? { ...x, is_hidden: !x.is_hidden } : x
        )
      );
    } catch {
      setСбой(true);
    } finally {
      setЗанят(null);
    }
  };

  if (сбой) {
    return (
      <EmptyState
        icon={WifiOff}
        title="Не удалось загрузить"
        description="Проверьте соединение и попробуйте снова."
        action={
          <Button variant="secondary" size="md" onClick={загрузить}>
            Повторить
          </Button>
        }
      />
    );
  }

  if (!stories) {
    return (
      <div className="flex flex-col gap-2">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-24 rounded-[var(--radius-tile)]" />
        ))}
      </div>
    );
  }

  return (
    <div>
      <label className="flex items-center gap-2 mb-3 text-[13.5px] text-text-muted">
        <input
          type="checkbox"
          checked={толькоВидимые}
          onChange={(e) => setТолькоВидимые(e.target.checked)}
          className="w-4 h-4 accent-[var(--color-accent)]"
        />
        Только те, что сейчас показываются
      </label>

      {stories.length === 0 ? (
        <EmptyState icon={Camera} title="Историй нет" />
      ) : (
        <div className="flex flex-col gap-2">
          {stories.map((s) => {
            const истекла = !!s.expires_at && new Date(s.expires_at) < new Date();
            return (
              <div
                key={s.id}
                className="flex items-center gap-3 p-3 rounded-[var(--radius-tile)]
                           bg-surface border border-hairline"
              >
                {/* История — фото, нарушение видно прямо по миниатюре */}
                <img
                  src={s.media_url}
                  alt=""
                  className={`w-16 h-20 object-cover rounded-[var(--radius-control)] shrink-0 ${
                    s.is_hidden || истекла ? "opacity-40" : ""
                  }`}
                />

                <div className="flex-1 min-w-0">
                  <p className="text-[14px] font-semibold truncate">
                    {s.author_name || s.author_id}
                  </p>
                  <p className="text-[13px] text-text-muted truncate">
                    {s.caption || "без подписи"}
                  </p>
                  <p className="text-[12px] text-text-faint">
                    {АУДИТОРИЯ[s.audience] ?? s.audience} · {s.views_count} просм.
                    {s.is_hidden && " · снята с показа"}
                    {истекла && " · истекла"}
                  </p>
                  <a
                    href={s.media_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-[12.5px] text-accent underline underline-offset-2"
                  >
                    Открыть кадр
                  </a>
                </div>

                {/* Истёкшая уже не показывается — снимать её поздно и
                    незачем, кнопка только жгла бы клики модератора */}
                {!истекла && (
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={занят === s.id}
                    onClick={() => действие(s)}
                  >
                    {s.is_hidden ? <Eye size={15} /> : <EyeOff size={15} />}
                    {s.is_hidden ? "Вернуть" : "Снять"}
                  </Button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
