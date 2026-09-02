/**
 * Выбор схемы оформления.
 *
 * Схему применяем сразу по нажатию, до ответа сервера: смена цвета —
 * жест примерки, и ожидание сети здесь ломает саму суть выбора. Сервер
 * догоняет, а при отказе (платная схема без подписки) откатываем.
 */
import { useEffect, useState, type CSSProperties } from "react";
import { Check, Lock } from "lucide-react";
import { Sheet } from "./Sheet";
import { Toggle } from "./ui";
import { useStore } from "../lib/store";
import { haptic } from "../lib/haptics";
import { recordSectionOpen, updateMyProfile } from "../lib/api";
import {
  APPEARANCES,
  applyAppearance,
  applyLivingMotion,
  loadAppearance,
  loadLivingMotion,
  type AppearanceKey,
} from "../lib/appearance";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Куда отправить за подпиской при попытке взять платную схему. */
  onNeedPlus: () => void;
}

export function AppearanceSheet({ open, onClose, onNeedPlus }: Props) {
  const user = useStore((s) => s.user);
  const setUser = useStore((s) => s.setUser);
  const [active, setActive] = useState<AppearanceKey>(() => loadAppearance());
  const [error, setError] = useState<string | null>(null);
  const [motion, setMotion] = useState<boolean>(() => loadLivingMotion());

  // Панель смонтирована вместе со страницей, поэтому считаем не
  // монтирование, а показ: иначе каждый заход в профиль выглядел бы
  // открытием раздела «оформление».
  useEffect(() => {
    if (open) recordSectionOpen("appearance");
  }, [open]);

  const выбрать = async (key: AppearanceKey) => {
    if (key === active) return;
    haptic("light");
    setError(null);

    const прежняя = active;
    setActive(key);
    applyAppearance(key);

    try {
      const обновлённый = await updateMyProfile({ app_theme: key });
      setUser(обновлённый);
    } catch (e: any) {
      setActive(прежняя);
      applyAppearance(прежняя);
      if (e?.response?.status === 403) {
        setError("Эта схема доступна с подпиской Plus");
        onNeedPlus();
      } else {
        setError("Не удалось сохранить выбор — попробуй ещё раз");
      }
    }
  };

  // Движение орбов — настройка устройства, а не анкеты: применяется сразу,
  // без сети (см. applyLivingMotion).
  const переключитьДвижение = () => {
    haptic("light");
    const next = !motion;
    setMotion(next);
    applyLivingMotion(next);
  };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Оформление"
      subtitle="Схема применяется ко всему приложению и переезжает с тобой"
    >
      {error && (
        <div className="mb-3 rounded-[10px] border border-danger/30 bg-danger/10 px-3 py-2 text-[13px] text-danger">
          {error}
        </div>
      )}

      <div className="grid grid-cols-2 gap-2.5 pb-3">
        {APPEARANCES.map((a) => {
          const выбрана = a.key === active;
          const закрыта = Boolean(a.premium) && !user?.is_premium;

          return (
            <button
              key={a.key}
              onClick={() => (закрыта ? onNeedPlus() : выбрать(a.key))}
              className={`relative overflow-hidden rounded-[14px] border p-3 text-left transition-transform active:scale-[0.98] ${
                a.orbs ? "living-preview" : ""
              } ${выбрана ? "border-accent" : "border-hairline"}`}
              style={
                a.orbs
                  ? ({
                      background: a.swatch[0],
                      "--preview-canvas": a.swatch[0],
                      "--orb-1": a.orbs[0],
                      "--orb-2": a.orbs[1],
                      "--orb-3": a.orbs[2],
                      "--spark": a.spark ?? "transparent",
                    } as CSSProperties)
                  : { background: a.swatch[0] }
              }
            >
              {/* Предпросмотр — схема как она есть: орбы схемы на канве
                  (.living-preview) и две стеклянные плашки поверх, чтобы
                  было видно, как читаются поверхности. Светлые схемы без
                  орбов показывают плашки на ровной канве. */}
              <div className="mb-2.5 space-y-1.5">
                <div
                  className="h-4 w-3/5 rounded-full"
                  style={{ background: a.orbs ? "rgb(255 255 255 / 0.16)" : a.swatch[2] }}
                />
                <div
                  className="ml-auto h-4 w-2/5 rounded-full"
                  style={{ background: a.orbs ? "rgb(255 255 255 / 0.1)" : a.swatch[1] }}
                />
                <div
                  className="h-4 w-4/5 rounded-full"
                  style={{ background: a.orbs ? "rgb(255 255 255 / 0.1)" : a.swatch[1] }}
                />
              </div>

              <div className="flex items-center gap-1.5">
                <span
                  className="text-[14px] font-semibold"
                  style={{ color: a.key === "light" || a.key === "sepia" ? "#0d1017" : "#fafbfc" }}
                >
                  {a.name}
                </span>
                {закрыта && <Lock size={12} className="text-warn" />}
                {выбрана && (
                  <span
                    className="ml-auto grid h-5 w-5 place-items-center rounded-full"
                    style={{ background: a.swatch[2] }}
                  >
                    <Check size={13} color="#fff" strokeWidth={3} />
                  </span>
                )}
              </div>
              <p
                className="mt-0.5 text-[11.5px] leading-tight"
                style={{
                  color:
                    a.key === "light" || a.key === "sepia"
                      ? "rgb(13 16 23 / 0.6)"
                      : "rgb(250 251 252 / 0.55)",
                }}
              >
                {a.hint}
              </p>
            </button>
          );
        })}
      </div>

      <button
        onClick={переключитьДвижение}
        aria-pressed={motion}
        className="mb-3 flex w-full items-center gap-3 rounded-[14px] border border-hairline bg-surface px-3.5 py-3 text-left"
      >
        <div className="min-w-0 flex-1">
          <p className="text-[15px]">Живое движение</p>
          <p className="text-caption leading-snug text-text-muted">
            Орбы фона медленно плывут. Выключи, если отвлекает или бережёшь батарею
          </p>
        </div>
        <Toggle on={motion} />
      </button>
    </Sheet>
  );
}
