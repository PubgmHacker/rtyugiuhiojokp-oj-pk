import { useEffect, useState, useCallback } from "react";
import { EyeOff, Eye } from "lucide-react";
import { getAdminReels, moderateReel, type AdminReel } from "../../lib/admin";
import { Button, EmptyState, Skeleton } from "../ui";

/**
 * Очередь роликов для ручной проверки.
 *
 * AI смотрит только присланные кадры (10/50/90% длительности), и этого хватает
 * для явного нарушения, но не для всего: то, что начинается прилично, дальше
 * может быть любым. Без этого экрана снять ролик было невозможно вовсе —
 * эндпоинты на сервере были, а кнопки к ним не вело.
 *
 * Ролик не удаляем, а прячем: жалоба могла быть ложной, и вернуть удалённое
 * видео автору уже нечем.
 */
export default function ReelsTable() {
  const [reels, setReels] = useState<AdminReel[] | null>(null);
  const [сбой, setСбой] = useState(false);
  const [занят, setЗанят] = useState<string | null>(null);
  const [толькоВидимые, setТолькоВидимые] = useState(false);

  const загрузить = useCallback(() => {
    setСбой(false);
    setReels(null);
    getAdminReels(толькоВидимые)
      .then(setReels)
      .catch(() => setСбой(true));
  }, [толькоВидимые]);

  useEffect(загрузить, [загрузить]);

  const действие = async (r: AdminReel) => {
    setЗанят(r.id);
    try {
      await moderateReel(r.id, r.is_hidden ? "show" : "hide");
      // Обновляем на месте: перезагрузка списка сбрасывает прокрутку, а
      // модератор идёт по очереди сверху вниз
      setReels((прежние) =>
        (прежние ?? []).map((x) =>
          x.id === r.id ? { ...x, is_hidden: !x.is_hidden } : x
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
        emoji="📡"
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

  if (!reels) {
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
        Только те, что сейчас в ленте
      </label>

      {reels.length === 0 ? (
        <EmptyState emoji="🎬" title="Роликов нет" />
      ) : (
        <div className="flex flex-col gap-2">
          {reels.map((r) => (
            <div
              key={r.id}
              className="flex items-center gap-3 p-3 rounded-[var(--radius-tile)]
                         bg-surface border border-hairline"
            >
              {r.cover_url ? (
                <img
                  src={r.cover_url}
                  alt=""
                  className="w-16 h-20 object-cover rounded-[var(--radius-control)] shrink-0"
                />
              ) : (
                <div className="w-16 h-20 rounded-[var(--radius-control)] bg-surface-2 shrink-0" />
              )}

              <div className="flex-1 min-w-0">
                <p className="text-[14px] font-semibold truncate">
                  {r.author_name || r.author_id}
                </p>
                <p className="text-[13px] text-text-muted truncate">
                  {r.caption || "без подписи"}
                </p>
                <p className="text-[12px] text-text-faint">
                  ♥ {r.likes_count}
                  {r.is_hidden && " · снят с показа"}
                </p>
                {/* Ссылка на само видео: по обложке нарушение не увидеть, а
                    именно ради этого экран и нужен */}
                <a
                  href={r.video_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-[12.5px] text-accent underline underline-offset-2"
                >
                  Смотреть видео
                </a>
              </div>

              <Button
                variant="secondary"
                size="sm"
                disabled={занят === r.id}
                onClick={() => действие(r)}
              >
                {r.is_hidden ? <Eye size={15} /> : <EyeOff size={15} />}
                {r.is_hidden ? "Вернуть" : "Снять"}
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
