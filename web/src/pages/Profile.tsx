import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  LogOut,
  Pencil,
  Shield,
  Crown,
  Gift,
  Copy,
  Check,
  MapPin,
  Trash2,
  FileText,
  ChevronRight,
  AlertTriangle,
  Ban,
} from "lucide-react";
import {
  getMyProfile,
  updateMyProfile,
  deleteMyAccount,
  getBlockedUsers,
  unblockUser,
  type UserProfile,
} from "../lib/api";
import { useStore } from "../lib/store";
import { haptic } from "../lib/haptics";
import { getCurrentPosition, openExternal } from "../lib/native";
import { Button, Card, Chip, Skeleton, VerifiedBadge, Spinner } from "../components/ui";
import PremiumOffer from "../components/PremiumOffer";

const BOT_USERNAME = import.meta.env.VITE_BOT_USERNAME || "souldawn_dating_bot";
const SITE_URL = import.meta.env.VITE_SITE_URL || "https://souldawn.app";

export default function Profile() {
  const navigate = useNavigate();
  const { logout } = useStore();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [geoStatus, setGeoStatus] = useState<"idle" | "busy" | "ok" | "fail">("idle");
  const [incognitoBusy, setIncognitoBusy] = useState(false);
  const [linkCopied, setLinkCopied] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  // Блокировку нужно уметь снять — иначе функция незакончена и человек
  // не может исправить случайный тап
  const [blocked, setBlocked] = useState<UserProfile[] | null>(null);
  const [blockedOpen, setBlockedOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      setProfile(await getMyProfile());
    } catch {
      /* экран останется с прежними данными */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openBlocked = useCallback(async () => {
    haptic("light");
    setBlockedOpen(true);
    try {
      setBlocked(await getBlockedUsers());
    } catch {
      setBlocked([]);
    }
  }, []);

  const handleUnblock = useCallback(async (id: string, name: string) => {
    if (
      !window.confirm(
        `Разблокировать ${name || "этого пользователя"}?\n\nМэтч и переписка не вернутся — знакомиться придётся заново.`
      )
    )
      return;
    try {
      await unblockUser(id);
      setBlocked((list) => (list ?? []).filter((u) => u.id !== id));
      haptic("success");
    } catch {
      haptic("error");
    }
  }, []);

  const handleGeolocate = useCallback(async () => {
    setGeoStatus("busy");
    const pos = await getCurrentPosition();
    if (!pos) {
      setGeoStatus("fail");
      haptic("error");
      return;
    }
    try {
      await updateMyProfile({ latitude: pos.latitude, longitude: pos.longitude });
      setProfile((p) => (p ? { ...p, has_location: true } : p));
      setGeoStatus("ok");
      haptic("success");
    } catch {
      setGeoStatus("fail");
      haptic("error");
    }
  }, []);

  const toggleIncognito = useCallback(async () => {
    if (!profile || incognitoBusy) return;
    setIncognitoBusy(true);
    haptic("light");
    try {
      setProfile(await updateMyProfile({ is_incognito: !profile.is_incognito }));
    } catch {
      haptic("error");
    } finally {
      setIncognitoBusy(false);
    }
  }, [profile, incognitoBusy]);

  const referralLink = profile
    ? `https://t.me/${BOT_USERNAME}?start=ref_${profile.id}`
    : "";

  const copyReferralLink = useCallback(async () => {
    haptic("light");
    try {
      await navigator.clipboard.writeText(referralLink);
      setLinkCopied(true);
      setTimeout(() => setLinkCopied(false), 2000);
    } catch {
      // Буфер обмена недоступен вне https — показываем ссылку текстом
      window.prompt("Скопируйте ссылку:", referralLink);
    }
  }, [referralLink]);

  if (loading) {
    return (
      <div className="max-w-[440px] mx-auto px-4 safe-top">
        <div className="flex flex-col items-center pt-6 pb-8">
          <Skeleton className="w-[104px] h-[104px] rounded-full mb-4" />
          <Skeleton className="w-40 h-6 mb-2" />
          <Skeleton className="w-24 h-4" />
        </div>
        <Skeleton className="h-20 mb-4" />
        <Skeleton className="h-32 mb-4" />
        <Skeleton className="h-32" />
      </div>
    );
  }

  const photo = profile?.photos?.[0];

  return (
    <div className="max-w-[440px] mx-auto px-4 safe-top pb-8">
      {/* ── Шапка профиля ─────────────────────────────────────── */}
      <div className="flex flex-col items-center pt-5 pb-7">
        <div className="relative mb-4">
          <div className="w-[104px] h-[104px] rounded-full ring-dawn overflow-hidden">
            {photo ? (
              <img
                src={photo}
                alt={profile?.display_name ?? ""}
                className="w-full h-full object-cover rounded-full"
              />
            ) : (
              <div
                className="w-full h-full rounded-full flex items-center justify-center
                           text-3xl font-bold text-white/60"
                style={{ background: "var(--gradient-placeholder)" }}
              >
                {profile?.display_name?.[0]?.toUpperCase() ?? "?"}
              </div>
            )}
          </div>
          {profile?.is_premium && (
            <span
              className="absolute -bottom-1 left-1/2 -translate-x-1/2 px-2.5 py-0.5
                         rounded-full bg-dawn text-[10px] font-bold text-white
                         flex items-center gap-1 whitespace-nowrap"
            >
              <Crown size={10} fill="currentColor" />
              PREMIUM
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 mb-1">
          <h1 className="text-title font-extrabold">
            {profile?.display_name || "Без имени"}
          </h1>
          {profile?.is_verified && <VerifiedBadge size={20} />}
        </div>

        <p className="text-text-muted text-[14px]">
          {profile?.age ? `${profile.age} · ` : ""}
          {profile?.city || "Город не указан"}
        </p>

        <Button
          variant="secondary"
          size="sm"
          className="mt-4"
          onClick={() => navigate("/onboarding")}
        >
          <Pencil size={15} />
          Редактировать анкету
        </Button>
      </div>

      {/* ── Статистика ────────────────────────────────────────── */}
      <div className="grid grid-cols-3 gap-2.5 mb-5">
        <Stat label="Фото" value={profile?.photos?.length ?? 0} />
        <Stat label="Интересы" value={profile?.interests?.length ?? 0} />
        <Stat
          label="Приглашено"
          value={profile?.invited_count ?? 0}
        />
      </div>

      {/* ── О себе ────────────────────────────────────────────── */}
      {profile?.bio && (
        <Card className="p-4 mb-4">
          <h2 className="text-caption text-text-muted mb-1.5">О себе</h2>
          <p className="text-[15px] leading-relaxed selectable">{profile.bio}</p>
        </Card>
      )}

      {/* ── Интересы ──────────────────────────────────────────── */}
      {!!profile?.interests?.length && (
        <div className="mb-5">
          <h2 className="text-caption text-text-muted mb-2.5 px-1">Интересы</h2>
          <div className="flex flex-wrap gap-2">
            {profile.interests.map((i) => (
              <Chip key={i}>{i}</Chip>
            ))}
          </div>
        </div>
      )}

      {/* ── Геолокация ────────────────────────────────────────── */}
      <Card className="p-4 mb-4">
        <div className="flex items-start gap-3">
          <MapPin size={18} className="text-accent mt-0.5 shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="font-semibold text-[15px] mb-0.5">Поиск рядом</p>
            <p className="text-caption text-text-muted">
              {geoStatus === "ok"
                ? "Местоположение обновлено"
                : geoStatus === "fail"
                  ? "Не удалось определить — проверьте доступ к геопозиции"
                  : profile?.has_location
                    ? "Включён — вы видите расстояние до людей"
                    : "Включите, чтобы видеть людей поблизости"}
            </p>
          </div>
        </div>
        <Button
          variant="secondary"
          size="sm"
          fullWidth
          className="mt-3"
          onClick={handleGeolocate}
          disabled={geoStatus === "busy"}
        >
          {geoStatus === "busy" ? (
            <Spinner size={16} />
          ) : profile?.has_location ? (
            "Обновить местоположение"
          ) : (
            "Определить местоположение"
          )}
        </Button>
      </Card>

      {/* ── Premium ───────────────────────────────────────────── */}
      {profile?.is_premium ? (
        <Card className="p-4 mb-4 border-accent/25">
          <div className="flex items-center gap-2.5 mb-3.5">
            <Crown size={18} className="text-accent" />
            <span className="font-bold text-[15px] flex-1">Premium активен</span>
          </div>

          <button
            onClick={toggleIncognito}
            disabled={incognitoBusy}
            className="w-full flex items-center gap-3 disabled:opacity-50"
          >
            <Shield
              size={18}
              className={profile.is_incognito ? "text-success" : "text-text-muted"}
            />
            <span className="flex-1 text-left text-[15px]">Инкогнито</span>
            <Toggle on={!!profile.is_incognito} />
          </button>
        </Card>
      ) : (
        <PremiumOffer userId={profile?.id || ""} onPurchased={load} />
      )}

      {/* ── Реферальная программа ─────────────────────────────── */}
      <Card className="p-4 mb-4">
        <div className="flex items-center gap-2.5 mb-2">
          <Gift size={18} className="text-accent" />
          <span className="font-semibold text-[15px]">Приглашай друзей</span>
        </div>

        {profile?.referral_boost ? (
          <p className="text-[14px] text-success mb-3.5">
            Буст активен: анкета выше на {profile.referral_boost_percent ?? 12}%
          </p>
        ) : (
          <>
            <p className="text-[14px] text-text-secondary mb-3">
              Пригласите {profile?.referral_target ?? 3} друзей и получите буст
              анкеты на {profile?.referral_boost_percent ?? 12}%
            </p>
            <div className="flex gap-1.5 mb-1.5">
              {Array.from({ length: profile?.referral_target ?? 3 }).map((_, i) => (
                <div
                  key={i}
                  className={`h-1.5 flex-1 rounded-full ${
                    i < (profile?.invited_count ?? 0) ? "bg-dawn" : "bg-surface-3"
                  }`}
                />
              ))}
            </div>
            <p className="text-caption text-text-muted mb-3.5">
              {profile?.invited_count ?? 0} из {profile?.referral_target ?? 3}
            </p>
          </>
        )}

        <Button variant="secondary" size="sm" fullWidth onClick={copyReferralLink}>
          {linkCopied ? <Check size={15} /> : <Copy size={15} />}
          {linkCopied ? "Ссылка скопирована" : "Скопировать приглашение"}
        </Button>
      </Card>

      {/* ── Заблокированные ──────────────────────────────────── */}
      <div className="mb-4 rounded-[var(--radius-tile)] border border-hairline overflow-hidden">
        <button
          onClick={() => (blockedOpen ? setBlockedOpen(false) : openBlocked())}
          className="w-full flex items-center gap-3 px-4 py-3.5 bg-surface
                     active:bg-surface-2 transition-colors"
        >
          <Ban size={17} className="text-text-muted shrink-0" />
          <span className="flex-1 text-left text-[15px]">Заблокированные</span>
          <ChevronRight
            size={17}
            className={`text-text-faint shrink-0 transition-transform ${
              blockedOpen ? "rotate-90" : ""
            }`}
          />
        </button>

        <AnimatePresence initial={false}>
          {blockedOpen && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden border-t border-hairline bg-surface-2"
            >
              {blocked === null ? (
                <div className="flex justify-center py-4">
                  <Spinner size={18} />
                </div>
              ) : blocked.length === 0 ? (
                <p className="px-4 py-3.5 text-[13.5px] text-text-muted">
                  Вы никого не блокировали.
                </p>
              ) : (
                blocked.map((u, i) => (
                  <div
                    key={u.id}
                    className={`flex items-center gap-3 px-4 py-2.5
                                ${i > 0 ? "border-t border-hairline" : ""}`}
                  >
                    <div className="w-8 h-8 rounded-full overflow-hidden bg-surface shrink-0">
                      {u.photos?.[0] && (
                        <img src={u.photos[0]} alt="" className="w-full h-full object-cover" />
                      )}
                    </div>
                    <span className="flex-1 text-[14px] truncate">
                      {u.display_name || "Без имени"}
                    </span>
                    <button
                      onClick={() => handleUnblock(u.id, u.display_name || "")}
                      className="text-[13px] text-accent font-medium tap-target px-1"
                    >
                      Разблокировать
                    </button>
                  </div>
                ))
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* ── Документы и правила ───────────────────────────────── */}
      <div className="mb-4 rounded-[var(--radius-tile)] border border-hairline overflow-hidden">
        {[
          { label: "Правила сообщества", path: "/guidelines.html" },
          { label: "Политика конфиденциальности", path: "/privacy.html" },
          { label: "Условия использования", path: "/terms.html" },
          { label: "Поддержка", path: "/support.html" },
        ].map((item, i) => (
          <button
            key={item.path}
            onClick={() => {
              haptic("light");
              openExternal(`${SITE_URL}${item.path}`);
            }}
            className={`w-full flex items-center gap-3 px-4 py-3.5 bg-surface
                        active:bg-surface-2 transition-colors
                        ${i > 0 ? "border-t border-hairline" : ""}`}
          >
            <FileText size={17} className="text-text-muted shrink-0" />
            <span className="flex-1 text-left text-[15px]">{item.label}</span>
            <ChevronRight size={17} className="text-text-faint shrink-0" />
          </button>
        ))}
      </div>

      {/* ── Аккаунт ───────────────────────────────────────────── */}
      <div className="flex flex-col gap-2.5">
        <Button
          variant="secondary"
          size="md"
          fullWidth
          onClick={() => {
            logout();
            navigate("/login", { replace: true });
          }}
        >
          <LogOut size={17} />
          Выйти
        </Button>

        <Button
          variant="danger"
          size="md"
          fullWidth
          onClick={() => {
            haptic("warning");
            setDeleteOpen(true);
          }}
        >
          <Trash2 size={17} />
          Удалить аккаунт
        </Button>
      </div>

      <DeleteAccountDialog
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        onDeleted={() => {
          logout();
          navigate("/login", { replace: true });
        }}
      />
    </div>
  );
}

/* ── Вспомогательные компоненты ─────────────────────────────── */

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="text-center py-3.5 rounded-[var(--radius-tile)] bg-surface border border-hairline">
      <p className="text-[22px] font-extrabold leading-none mb-1">{value}</p>
      <p className="text-[11.5px] text-text-muted">{label}</p>
    </div>
  );
}

function Toggle({ on }: { on: boolean }) {
  return (
    <span
      className={`w-[46px] h-[27px] rounded-full relative shrink-0 transition-colors ${
        on ? "bg-success" : "bg-surface-3"
      }`}
    >
      <motion.span
        layout
        transition={{ type: "spring", stiffness: 520, damping: 32 }}
        className="absolute top-[3px] w-[21px] h-[21px] bg-white rounded-full"
        style={{ left: on ? 22 : 3 }}
      />
    </span>
  );
}

/**
 * Удаление аккаунта в два шага — требование App Store: функция должна
 * быть доступна внутри приложения, но защищена от случайного нажатия.
 */
function DeleteAccountDialog({
  open,
  onClose,
  onDeleted,
}: {
  open: boolean;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [confirmText, setConfirmText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const canDelete = confirmText.trim().toUpperCase() === "УДАЛИТЬ";

  const submit = async () => {
    if (!canDelete || busy) return;
    setBusy(true);
    setError("");
    try {
      await deleteMyAccount();
      haptic("success");
      onDeleted();
    } catch {
      setError("Не удалось удалить аккаунт. Попробуйте позже.");
      haptic("error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-50 bg-black/75 backdrop-blur-md"
          />
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label="Удаление аккаунта"
            initial={{ opacity: 0, scale: 0.92, y: 24 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.94 }}
            transition={{ type: "spring", stiffness: 360, damping: 28 }}
            className="fixed inset-x-4 top-1/2 -translate-y-1/2 z-50 max-w-[360px] mx-auto
                       bg-bg-elevated border border-hairline rounded-[var(--radius-sheet)]
                       p-6 card-shadow"
          >
            <div className="flex justify-center mb-4">
              <div className="w-14 h-14 rounded-full bg-danger/15 flex items-center justify-center">
                <AlertTriangle size={26} className="text-danger" />
              </div>
            </div>

            <h2 className="text-heading font-bold text-center mb-2">
              Удалить аккаунт?
            </h2>
            <p className="text-[14px] text-text-secondary text-center leading-relaxed mb-5">
              Будут безвозвратно удалены анкета, фотографии, мэтчи и вся
              переписка. Это действие нельзя отменить.
            </p>

            <label className="block text-caption text-text-muted mb-2">
              Введите «УДАЛИТЬ» для подтверждения
            </label>
            <input
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              autoCapitalize="characters"
              className="w-full px-4 h-12 mb-4 rounded-full bg-surface border border-hairline
                         text-center tracking-wider outline-none
                         focus:border-danger transition-colors"
              placeholder="УДАЛИТЬ"
            />

            {error && (
              <p className="text-[13px] text-danger text-center mb-3">{error}</p>
            )}

            <div className="flex flex-col gap-2.5">
              <Button
                variant="danger"
                size="md"
                fullWidth
                disabled={!canDelete || busy}
                onClick={submit}
              >
                {busy ? <Spinner size={18} /> : "Удалить навсегда"}
              </Button>
              <Button variant="ghost" size="md" fullWidth onClick={onClose}>
                Отмена
              </Button>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
