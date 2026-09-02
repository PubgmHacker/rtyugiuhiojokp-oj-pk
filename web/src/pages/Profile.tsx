import { useEffect, useState, useCallback } from "react";
import { useNavigate, Link } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { askConfirm } from "../lib/telegram";
import {
  BadgeCheck,
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
  Download,
  ChevronRight,
  AlertTriangle,
  Eye,
  EyeOff,
  Film,
  Star,
  Ban,
  Send,
  X,
  Palette,
  Languages,
} from "lucide-react";
import {
  getMyProfile,
  updateMyProfile,
  deleteMyAccount,
  exportMyData,
  getBlockedUsers,
  getMyReels,
  getMyVisitors,
  unblockUser,
  logoutEverywhere,
  type UserProfile,
  type VisitorsOut,
  type Reel as ReelType,
} from "../lib/api";
import { useStore } from "../lib/store";
import { AppearanceSheet } from "../components/AppearanceSheet";
import { LanguageSheet } from "../components/LanguageSheet";
import { НАЗВАНИЯ, useT, useЯзык } from "../lib/i18n";
import { VerificationSheet } from "../components/VerificationSheet";
import { appearanceByKey, loadAppearance } from "../lib/appearance";
import { haptic } from "../lib/haptics";
import { legalUrl } from "../lib/legal";
import { getCurrentPosition, openExternal } from "../lib/native";
import { Button, Card, Chip, LoadError, Skeleton, Toggle, VerifiedBadge, Spinner } from "../components/ui";
import EmailRecovery from "../components/EmailRecovery";

const BOT_USERNAME = import.meta.env.VITE_BOT_USERNAME || "simpmatchbot";

export default function Profile() {
  const navigate = useNavigate();
  const { logout } = useStore();
  // Пауза видна и в оболочке приложения (PauseBanner), а та читает store.
  // Поэтому переключатель обязан обновить и его: иначе плашка «анкета на
  // паузе» осталась бы висеть после того, как паузу здесь уже сняли
  const setUser = useStore((s) => s.setUser);
  const t = useT();
  const язык = useЯзык();
  const [выходВезде, setВыходВезде] = useState(false);
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
  // Сбой показываем, только пока списка нет вовсе: провалившееся фоновое
  // обновление уже показанных не стирает
  const [blockedСбой, setBlockedСбой] = useState(false);
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const [languageOpen, setLanguageOpen] = useState(false);
  const [verifyOpen, setVerifyOpen] = useState(false);
  const [exportState, setExportState] = useState<"idle" | "busy" | "fail">("idle");
  // Какой тумблер приватности сейчас сохраняется — блокируем только его,
  // а не всю секцию: остальные переключать можно
  const [privacyBusy, setPrivacyBusy] = useState<string | null>(null);
  // Пауза — отдельным состоянием от privacyBusy: у неё есть видимый текст
  // ошибки, которого у остальных тумблеров нет. Молча провалившаяся пауза
  // хуже любой другой молча провалившейся настройки — человек уверен, что
  // скрылся, а он на витрине
  const [pauseBusy, setPauseBusy] = useState(false);
  const [pauseError, setPauseError] = useState("");
  // Что открываем после входа: лента или видео (как у референса)
  const [mainScreen, setMainScreen] = useState<"feed" | "reels">(
    () => (localStorage.getItem("sd_main_screen") as "feed" | "reels" | null) ?? "feed",
  );

  useEffect(() => {
    localStorage.setItem("sd_main_screen", mainScreen);
  }, [mainScreen]);

  const togglePrivacy = useCallback(
    async (
      field: "hide_age" | "hide_distance" | "hide_from_visitors" | "hide_from_ratings",
      value: boolean,
    ) => {
      haptic("light");
      setPrivacyBusy(field);
      try {
        setProfile(await updateMyProfile({ [field]: value }));
      } catch {
        haptic("error");
      } finally {
        setPrivacyBusy(null);
      }
    },
    []
  );

  // Пауза: убрать анкету из выдачи, не удаляя аккаунт. Уровнем подписки не
  // ограничена — уйти с витрины должен уметь каждый, иначе единственная
  // альтернатива у бесплатного аккаунта — удаление.
  const togglePause = useCallback(
    async (value: boolean) => {
      if (pauseBusy) return;
      haptic("light");
      setPauseBusy(true);
      setPauseError("");
      try {
        const свежий = await updateMyProfile({ is_paused: value });
        setProfile(свежий);
        // И в store — плашку в оболочке рисует он
        setUser(свежий);
        haptic("success");
      } catch {
        setPauseError(
          value
            ? "Не удалось поставить на паузу. Анкета по-прежнему видна — попробуйте ещё раз"
            : "Не удалось снять паузу. Анкета всё ещё скрыта — попробуйте ещё раз"
        );
        haptic("error");
      } finally {
        setPauseBusy(false);
      }
    },
    [pauseBusy, setUser]
  );

  const load = useCallback(async () => {
    try {
      const свежий = await getMyProfile();
      setProfile(свежий);
      // Store тоже: паузу можно включить в боте, и тогда единственный способ
      // узнать о ней — этот запрос. Плашку в оболочке рисует store, поэтому
      // без синхронизации она молчала бы до следующего входа
      setUser(свежий);
    } catch {
      /* экран останется с прежними данными */
    } finally {
      setLoading(false);
    }
  }, [setUser]);

  useEffect(() => {
    load();
  }, [load]);

  const openBlocked = useCallback(async () => {
    haptic("light");
    setBlockedOpen(true);
    setBlockedСбой(false);
    try {
      setBlocked(await getBlockedUsers());
    } catch {
      // Пустой список при упавшей сети читался бы как «вы никого не
      // блокировали» — а человек пришёл сюда именно разблокировать
      setBlockedСбой(true);
    }
  }, []);

  // Выгрузка своих данных: бэкенд отдаёт JSON-файл, браузеру нужен
  // временный object URL, иначе Blob никак не попадёт на диск.
  const handleExport = useCallback(async () => {
    haptic("light");
    setExportState("busy");
    try {
      const blob = await exportMyData();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "simp-my-data.json";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setExportState("idle");
    } catch {
      setExportState("fail");
    }
  }, []);

  const handleUnblock = useCallback(async (id: string, name: string) => {
    const ok = await askConfirm(
      `Разблокировать ${name || "этого пользователя"}?\n\nМэтч и переписка не вернутся — знакомиться придётся заново.`
    );
    if (!ok) return;
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

  // Скелетон уже позади, а профиля нет — значит, первая загрузка упала.
  // Экран из «?» и пустых тумблеров выглядел бы как стёртая анкета
  if (!profile) {
    return (
      <div className="max-w-[440px] mx-auto px-4 safe-top">
        <LoadError
          onRetry={() => {
            setLoading(true);
            load();
          }}
        />
      </div>
    );
  }

  return (
    <div className="max-w-[440px] mx-auto px-4 safe-top pb-8">
      {/* ── Шапка профиля ─────────────────────────────────────── */}
      <div className="flex flex-col items-center pt-5 pb-7">
        <div className="relative mb-4">
          <div className="w-[104px] h-[104px] rounded-full avatar-ring overflow-hidden">
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
          {/* Своя наклейка из кейсов — на аватаре, там же, где её видят
              другие. Иначе надетое оформление нигде не видно самому себе */}
          {profile?.sticker && (
            <img
              src={profile.sticker}
              alt=""
              draggable={false}
              className="absolute -top-2 -right-3 w-11 h-11 rotate-6 select-none
                         drop-shadow-[0_2px_6px_rgba(0,0,0,.5)]"
            />
          )}
          {profile?.is_premium && (
            <span
              className="absolute -bottom-1 left-1/2 -translate-x-1/2 px-2.5 py-0.5
                         rounded-full bg-accent text-[10px] font-bold text-white
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
          onClick={() => navigate("/edit")}
        >
          <Pencil size={15} />
          Редактировать анкету
        </Button>
      </div>

      {/* ── Статистика ────────────────────────────────────────── */}
      <div className="grid grid-cols-3 gap-2.5 mb-5">
        <Stat label="Фото" value={profile?.photos?.length ?? 0} />
        <Stat label="Интересы" value={profile?.interests?.length ?? 0} />
        <Stat label="Приглашено" value={profile?.invited_count ?? 0} />
      </div>

      {/* ── Заполненность анкеты ──────────────────────────────── */}
      <ProfileCompleteness profile={profile} onEdit={() => navigate("/edit")} />
      {/* Точечный nudge: подталкивает закрыть одно дешёвое поле, а не весь %
          прогресса сразу — конверсия выше */}
      <NudgeBanner
        profile={profile}
        onJump={(field) => navigate(`/edit?focus=${field}`)}
      />

      {/* ── Проверка профиля (галочка) ────────────────────────── */}
      {/* Только пока галочки нет: подтверждённому этот вход не нужен,
          его галочка уже стоит рядом с именем */}
      {profile && !profile.is_verified && (
        <button
          onClick={() => {
            haptic("light");
            setVerifyOpen(true);
          }}
          className="w-full text-left mb-4 p-4 rounded-[var(--radius-tile)]
                     bg-surface border border-hairline flex items-center gap-3"
        >
          <BadgeCheck
            size={18}
            className="shrink-0"
            style={{ color: "var(--color-verified)" }}
          />
          <div className="flex-1 min-w-0">
            <p className="font-semibold text-[15px]">Подтвердите профиль</p>
            <p className="text-caption text-text-muted">
              Галочка за живую проверку — займёт полминуты
            </p>
          </div>
          <ChevronRight size={18} className="text-text-faint shrink-0" />
        </button>
      )}
      <VerificationSheet
        open={verifyOpen}
        onClose={() => setVerifyOpen(false)}
        onVerified={() =>
          setProfile((p) => (p ? { ...p, is_verified: true } : p))
        }
        onAddPhoto={() => {
          setVerifyOpen(false);
          navigate("/edit?focus=photos");
        }}
      />

      {/* ── О себе ────────────────────────────────────────────── */}
      {profile?.bio && (
        <Card className="p-4 mb-4">
          <h2 className="text-caption text-text-muted mb-1.5">О себе</h2>
          <p className="text-[15px] leading-relaxed selectable">{profile.bio}</p>
        </Card>
      )}

      {/* ── Гости ─────────────────────────────────────────────── */}
      <VisitorsCard />

      {/* ── Мои ролики ────────────────────────────────────────── */}
      <MyReelsCard />

      {/* ── Кейсы ─────────────────────────────────────────────── */}
      <Link
        to="/cases"
        onClick={() => haptic("light")}
        className="w-full text-left mb-4 p-4 rounded-[var(--radius-tile)]
                   bg-surface border border-hairline flex items-center gap-3"
      >
        <Gift size={18} className="text-accent shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-[15px]">Кейсы</p>
          <p className="text-caption text-text-muted">
            Наклейки и обложки для анкеты
          </p>
        </div>
        <ChevronRight size={18} className="text-text-faint shrink-0" />
      </Link>

      {/* ── Оценка фото ───────────────────────────────────────── */}
      {/* Вход в отдельный формат: и оценить чужие, и посмотреть свою оценку */}
      <Link
        to="/photo-ratings"
        onClick={() => haptic("light")}
        className="w-full text-left mb-4 p-4 rounded-[var(--radius-tile)]
                   bg-surface border border-hairline flex items-center gap-3"
      >
        <Star size={18} className="text-accent shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-[15px]">Оценка фото</p>
          <p className="text-caption text-text-muted">
            Оцените чужие и узнайте оценку своего
          </p>
        </div>
        <ChevronRight size={18} className="text-text-faint shrink-0" />
      </Link>

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
            <span className="font-bold text-[15px] flex-1">Подписка активна</span>
            {/* Продлить или перейти на старший уровень — тоже отсюда */}
            <Link
              to="/plans"
              onClick={() => haptic("light")}
              className="text-[13px] font-semibold text-accent"
            >
              Изменить
            </Link>
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
            <div className="flex-1 text-left">
              <p className="text-[15px]">Инкогнито</p>
              <p className="text-caption text-text-muted">
                Анкета скрыта из ленты полностью
              </p>
            </div>
            <Toggle on={!!profile.is_incognito} />
          </button>
        </Card>
      ) : (
        // Витрина живёт на своей вкладке: тарифов теперь шесть, в карточку
        // профиля они не укладываются
        <Link
          to="/plans"
          onClick={() => haptic("light")}
          className="w-full text-left mb-4 p-4 rounded-[var(--radius-tile)]
                     border border-accent/25 bg-accent/8 flex items-center gap-3"
        >
          <Crown size={20} className="text-accent shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="font-bold text-[15px]">Симп Plus и Ultra</p>
            <p className="text-caption text-text-muted">
              Кто вас лайкнул, инкогнито и приоритет в выдаче
            </p>
          </div>
          <ChevronRight size={18} className="text-text-faint shrink-0" />
        </Link>
      )}

      {/* ── Почта для восстановления ──────────────────────────── */}
      {/* Стоит перед приватностью и удалением: это то, что спасает аккаунт,
          и человек должен наткнуться на неё раньше, чем на «удалить» */}
      <EmailRecovery
        email={profile?.email}
        onAttached={(email) =>
          setProfile((прежний) => (прежний ? { ...прежний, email } : прежний))
        }
      />

      {/* ── Приватность ───────────────────────────────────────── */}
      {/* Доступна всем: прятать настройки приватности за подписку — плохо по
          отношению к тем, кому просто некомфортно быть на виду */}
      <Card className="p-4 mb-4">
        <div className="flex items-center gap-2.5 mb-3.5">
          <EyeOff size={18} className="text-accent" />
          <span className="font-semibold text-[15px]">Приватность</span>
        </div>

        <div className="flex flex-col gap-3.5">
          {/* Пауза стоит первой и отделена линией: она сильнее трёх тумблеров
              ниже и делает их бессмысленными. Скрытому целиком человеку
              незачем прятать возраст */}
          <div className="pb-3.5 border-b border-hairline">
            <PrivacyToggle
              label="Поставить анкету на паузу"
              hint={
                profile?.is_paused
                  ? "Анкета скрыта: вас не видно ни в ленте, ни в лайках, ни в оценке фото. Переписки с мэтчами продолжают работать"
                  : "Убрать анкету из выдачи, не удаляя аккаунт. Включить обратно можно в любой момент"
              }
              on={!!profile?.is_paused}
              busy={pauseBusy}
              onToggle={() => togglePause(!profile?.is_paused)}
            />
            {pauseError && (
              <p
                role="alert"
                className="mt-2.5 px-3 py-2 rounded-[var(--radius-tile)]
                           bg-danger/12 border border-danger/30 text-danger text-[12.5px]"
              >
                {pauseError}
              </p>
            )}
          </div>

          <PrivacyToggle
            label="Скрыть возраст"
            hint="В карточке возраста не будет, но подбор по нему останется"
            on={!!profile?.hide_age}
            busy={privacyBusy === "hide_age"}
            onToggle={() => togglePrivacy("hide_age", !profile?.hide_age)}
          />
          <PrivacyToggle
            label="Скрыть расстояние"
            hint="Город останется — без него непонятно, где вы"
            on={!!profile?.hide_distance}
            busy={privacyBusy === "hide_distance"}
            onToggle={() => togglePrivacy("hide_distance", !profile?.hide_distance)}
          />
          <PrivacyToggle
            label="Не попадать в «Гости»"
            hint="Хозяин анкеты не увидит, что вы заходили"
            on={!!profile?.hide_from_visitors}
            busy={privacyBusy === "hide_from_visitors"}
            onToggle={() =>
              togglePrivacy("hide_from_visitors", !profile?.hide_from_visitors)
            }
          />
          <PrivacyToggle
            label="Не участвовать в оценке фото"
            hint="Вас не будут оценивать — и вы не сможете оценить других"
            on={!!profile?.hide_from_ratings}
            busy={privacyBusy === "hide_from_ratings"}
            onToggle={() =>
              togglePrivacy("hide_from_ratings", !profile?.hide_from_ratings)
            }
          />
        </div>
      </Card>

      {/* ── Оформление ────────────────────────────────────────── */}
      {/* Рядом с приватностью: это тоже «как меня видно», только глазами
          хозяина анкеты. Плитка в идиоме соседних строк настроек. */}
      <div className="mb-4 rounded-[var(--radius-tile)] border border-hairline overflow-hidden">
        <button
          onClick={() => {
            haptic("light");
            setAppearanceOpen(true);
          }}
          className="w-full flex items-center gap-3 px-4 py-3.5 bg-surface text-left
                     active:bg-surface-2 transition-colors"
        >
          <Palette size={17} className="shrink-0 text-text-muted" />
          <span className="flex-1 text-[15px] text-text">Оформление</span>
          <span className="flex items-center gap-2">
            {/* Три точки палитры вместо названия: цвет узнаётся быстрее слова,
                а название всё равно стоит рядом. */}
            <span className="flex gap-1">
              {appearanceByKey(loadAppearance()).swatch.map((c, i) => (
                <span
                  key={i}
                  className="h-3.5 w-3.5 rounded-full border border-hairline"
                  style={{ background: c }}
                />
              ))}
            </span>
            <span className="text-[14px] text-text-muted">
              {appearanceByKey(loadAppearance()).name}
            </span>
          </span>
        </button>
      </div>

      {/* ── Язык ──────────────────────────────────────────────── */}
      {/* Сразу под оформлением: обе строки про то, каким человек видит
          приложение. И это единственное место, где язык можно сменить — бот
          спрашивает его один раз на первом /start и команды смены не имеет. */}
      <div className="mb-4 rounded-[var(--radius-tile)] border border-hairline overflow-hidden">
        <button
          onClick={() => {
            haptic("light");
            setLanguageOpen(true);
          }}
          className="w-full flex items-center gap-3 px-4 py-3.5 bg-surface text-left
                     active:bg-surface-2 transition-colors"
        >
          <Languages size={17} className="shrink-0 text-text-muted" />
          <span className="flex-1 text-[15px] text-text">{t("lang.title")}</span>
          {/* Название на самом языке, как в списке: «Türkçe», а не «турецкий» —
              так человек находит строку, даже не читая подпись слева. lang
              нужен читалке, иначе она произнесёт его по правилам интерфейса. */}
          <span className="text-[14px] text-text-muted" lang={язык}>
            {НАЗВАНИЯ[язык]}
          </span>
        </button>
      </div>

      {/* ── Telegram-канал ─────────────────────────────────────── */}
      <TgChannelCard profile={profile} setProfile={setProfile} />

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
                    i < (profile?.invited_count ?? 0) ? "bg-accent" : "bg-surface-3"
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
              {blockedСбой && blocked === null ? (
                <div className="px-4 py-3.5">
                  <p className="text-[13.5px] text-text-muted mb-2.5">
                    📡 Не удалось загрузить
                  </p>
                  <Button variant="secondary" size="sm" onClick={openBlocked}>
                    Повторить
                  </Button>
                </div>
              ) : blocked === null ? (
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
        {(
          [
            { label: "Правила сообщества", page: "guidelines" },
            { label: "Политика конфиденциальности", page: "privacy" },
            { label: "Условия использования", page: "terms" },
            { label: "Поддержка", page: "support" },
          ] as const
        ).map((item, i) => (
          <button
            key={item.page}
            onClick={() => {
              haptic("light");
              // legalUrl, а не window.location.origin: в нативной сборке origin —
              // `capacitor://localhost`, и такую схему openExternal открыть не может
              // (Browser отбрасывает не-http, система про неё не знает). Кнопка
              // нажималась и не делала ничего.
              openExternal(legalUrl(item.page));
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

      {/* ── Кастомизация: какой экран открывать после входа ───────
          У Мимолёта это даётся, и сказывается на возврате: кто-то живёт в
          ленте, кто-то — в видеороликах */}
      <Card className="p-4 mb-4">
        <h2 className="text-caption text-text-muted mb-3">Главный экран</h2>
        <div className="flex gap-2.5">
          <ScreenChoice
            label="Лента"
            hint="Свайп анкет"
            active={mainScreen === "feed"}
            onPick={() => setMainScreen("feed")}
          />
          <ScreenChoice
            label="Видео"
            hint="Reels-лента"
            active={mainScreen === "reels"}
            onPick={() => setMainScreen("reels")}
          />
        </div>
      </Card>

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

        {/* Обычный выход чужую сессию не трогает: украденный токен живёт до
            72 часов. Этот гасит все разом — включая текущий */}
        <Button
          variant="secondary"
          size="md"
          fullWidth
          disabled={выходВезде}
          onClick={async () => {
            setВыходВезде(true);
            try {
              await logoutEverywhere();
            } catch {
              // Сервер недоступен — локально выйти всё равно даём
            }
            logout();
            navigate("/login", { replace: true });
          }}
        >
          {выходВезде ? <Spinner size={16} /> : <LogOut size={17} />}
          Выйти на всех устройствах
        </Button>

        <Button
          variant="secondary"
          size="md"
          fullWidth
          disabled={exportState === "busy"}
          onClick={handleExport}
        >
          {exportState === "busy" ? <Spinner size={17} /> : <Download size={17} />}
          {exportState === "busy" ? "Готовим файл…" : "Скачать мои данные"}
        </Button>
        {exportState === "fail" && (
          <p className="text-xs text-rose-400">
            Не удалось выгрузить данные. Попробуйте позже.
          </p>
        )}

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

      <AppearanceSheet
        open={appearanceOpen}
        onClose={() => setAppearanceOpen(false)}
        onNeedPlus={() => {
          setAppearanceOpen(false);
          navigate("/plans");
        }}
      />

      <LanguageSheet open={languageOpen} onClose={() => setLanguageOpen(false)} />

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

/** Строка настройки приватности: подпись, пояснение и тумблер. */
function PrivacyToggle({
  label,
  hint,
  on,
  busy,
  onToggle,
}: {
  label: string;
  hint: string;
  on: boolean;
  busy: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      onClick={onToggle}
      disabled={busy}
      aria-pressed={on}
      className="w-full flex items-center gap-3 text-left disabled:opacity-50"
    >
      <div className="flex-1 min-w-0">
        <p className="text-[15px]">{label}</p>
        <p className="text-caption text-text-muted leading-snug">{hint}</p>
      </div>
      {busy ? <Spinner size={18} /> : <Toggle on={on} />}
    </button>
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

/* ── Telegram-канал: показывается ссылкой в чужой карточке ──── */

function TgChannelCard({
  profile,
  setProfile,
}: {
  profile: UserProfile | null;
  setProfile: (p: UserProfile) => void;
}) {
  const [value, setValue] = useState(profile?.tg_channel ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setValue(profile?.tg_channel ?? "");
  }, [profile?.tg_channel]);

  // Фича платная (см. FEATURE_MIN_TIER["tg_channel"] на сервере) — пока
  // тариф не открыт, поле просто не показываем: пусто в profile.tg_channel
  // ничем не отличается от «фичи нет», а лишний диалог «нужна подписка»
  // на каждый заход в профиль был бы навязчивым
  if (!profile) return null;

  const save = async () => {
    haptic("light");
    setBusy(true);
    setError(null);
    try {
      setProfile(await updateMyProfile({ tg_channel: value }));
      haptic("success");
    } catch (e: any) {
      haptic("error");
      // Сервер отдаёт понятную причину: неверный формат или тариф не
      // позволяет — обе ошибки нужно прочитать, а не додумывать
      setError(e?.response?.data?.detail ?? "Не удалось сохранить");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="p-4 mb-4">
      <div className="flex items-center gap-2.5 mb-2">
        <Send size={18} className="text-accent" />
        <span className="font-semibold text-[15px]">Telegram-канал</span>
      </div>
      <p className="text-caption text-text-muted mb-3">
        Покажется ссылкой в вашей карточке. Юзернейм без @ — например,
        simp_channel.
      </p>
      <div className="flex gap-2">
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="username"
          maxLength={100}
          className="flex-1 px-4 h-11 rounded-full bg-surface border border-hairline
                     outline-none focus:border-accent transition-colors text-[14.5px]"
        />
        <Button
          variant="primary"
          size="md"
          disabled={busy || value === (profile.tg_channel ?? "")}
          onClick={save}
        >
          {busy ? <Spinner size={16} /> : "Сохранить"}
        </Button>
      </div>
      {error && <p className="text-[13px] text-danger mt-2">{error}</p>}
    </Card>
  );
}

/* ── Гости: кто заходил в анкету ────────────────────────────── */

function VisitorsCard() {
  const [period, setPeriod] = useState<"today" | "week" | "all">("all");
  const [data, setData] = useState<VisitorsOut | null>(null);
  // Пока грузим новый период, старые данные лучше не показывать —
  // иначе счётчик мигает старым числом при переключении таба
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setLoaded(false);
    getMyVisitors(period)
      .then((d) => {
        setData(d);
        setLoaded(true);
      })
      .catch(() => setData(null)); // раздел необязателен, молчим
  }, [period]);

  // Пока не знаем и когда гостей нет за всё время — блока нет: пустая
  // карточка «0 гостей» только занимает место на экране. Проверяем именно
  // по «all», чтобы карточка не пропадала целиком при переключении на
  // период, где гостей пока не набралось
  if (!loaded && !data) return null;
  if (data?.total === 0 && period === "all") return null;

  return (
    <Card className="p-4 mb-4">
      <div className="flex items-center gap-2.5 mb-3">
        <Eye size={18} className="text-accent" />
        <span className="font-semibold text-[15px] flex-1">Гости</span>
        {data && (
          <span className="text-caption text-text-muted">
            {data.total} {plural(data.total, "человек", "человека", "человек")}
          </span>
        )}
      </div>

      <div className="flex gap-2 mb-3">
        <Chip active={period === "today"} onClick={() => setPeriod("today")}>
          Сегодня
        </Chip>
        <Chip active={period === "week"} onClick={() => setPeriod("week")}>
          Неделя
        </Chip>
        <Chip active={period === "all"} onClick={() => setPeriod("all")}>
          Всё время
        </Chip>
      </div>

      {!data ? null : data.revealed ? (
        data.visitors.length === 0 ? (
          <p className="text-caption text-text-muted">
            За этот период гостей не было.
          </p>
        ) : (
        <div className="flex flex-wrap gap-2">
          {data.visitors.map((v) => (
            <div
              key={v.profile.id}
              className="flex items-center gap-2 pl-1 pr-3 py-1 rounded-full
                         bg-surface-2 border border-hairline"
            >
              {v.profile.photos?.[0] ? (
                <img
                  src={v.profile.photos[0]}
                  alt=""
                  loading="lazy"
                  className="w-7 h-7 rounded-full object-cover"
                />
              ) : (
                <span
                  className="w-7 h-7 rounded-full flex items-center justify-center
                             text-[12px] font-bold text-white/50"
                  style={{ background: "var(--gradient-placeholder)" }}
                >
                  {v.profile.display_name?.[0]?.toUpperCase() ?? "?"}
                </span>
              )}
              <span className="text-[13.5px]">
                {v.profile.display_name || "Аноним"}
                {v.profile.age ? `, ${v.profile.age}` : ""}
              </span>
              {v.profile.tg_channel && (
                <a
                  href={`https://t.me/${v.profile.tg_channel}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  className="text-[12px] text-accent hover:underline"
                >
                  @{v.profile.tg_channel}
                </a>
              )}
              {v.visits > 1 && (
                <span className="text-[12px] text-text-muted">×{v.visits}</span>
              )}
            </div>
          ))}
        </div>
        )
      ) : (
        // Число гостей показываем всем: скрыв и его, мы не дали бы повода
        // купить — человек не знает, что к нему вообще кто-то заходил
        <Link
          to="/plans"
          onClick={() => haptic("light")}
          className="flex items-center gap-2.5 px-3.5 py-2.5 rounded-[var(--radius-tile)]
                     border border-accent/25 bg-accent/8"
        >
          <Crown size={16} className="text-accent shrink-0" />
          <span className="flex-1 text-[13.5px]">Узнать, кто заходил — в Ultra</span>
          <ChevronRight size={16} className="text-text-faint shrink-0" />
        </Link>
      )}
    </Card>
  );
}

function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

/* ── Заполненность анкеты ───────────────────────────────────── */

/**
 * Что считаем заполненным и сколько это стоит в процентах.
 *
 * Веса не равные: без фото и имени анкету не показывают вовсе, а MBTI — приятное
 * дополнение. Сумма ровно 100, иначе «100%» не достигалось бы никогда.
 */
const COMPLETENESS: {
  key: string;
  label: string;
  weight: number;
  done: (p: UserProfile) => boolean;
}[] = [
  { key: "name", label: "Имя", weight: 10, done: (p) => !!p.display_name },
  { key: "photo", label: "Хотя бы одно фото", weight: 20, done: (p) => !!p.photos?.length },
  {
    key: "photos",
    // Метка попадает в строку «Осталось: …» в нижнем регистре — форма
    // «минимум три фото» читается там как продолжение фразы
    label: "Минимум три фото",
    weight: 15,
    done: (p) => (p.photos?.length ?? 0) >= 3,
  },
  { key: "bio", label: "Пара слов о себе", weight: 15, done: (p) => !!p.bio },
  {
    key: "interests",
    label: "Интересы",
    weight: 10,
    done: (p) => !!p.interests?.length,
  },
  { key: "city", label: "Город", weight: 10, done: (p) => !!p.city },
  { key: "goal", label: "Цель знакомства", weight: 10, done: (p) => !!p.goal },
  {
    key: "subculture",
    label: "Субкультура",
    weight: 5,
    done: (p) => !!p.subculture,
  },
  { key: "height", label: "Рост", weight: 3, done: (p) => p.height_cm != null },
  { key: "mbti", label: "Тип личности", weight: 2, done: (p) => !!p.mbti },
];

function ProfileCompleteness({
  profile,
  onEdit,
}: {
  profile: UserProfile | null;
  onEdit: () => void;
}) {
  if (!profile) return null;

  const filled = COMPLETENESS.filter((item) => item.done(profile));
  const percent = filled.reduce((sum, item) => sum + item.weight, 0);
  const missing = COMPLETENESS.filter((item) => !item.done(profile));

  // Полностью заполненную анкету не дёргаем: подсказка «всё готово» ничего не
  // добавляет и только занимает место
  if (!missing.length) return null;

  return (
    <Card className="p-4 mb-4">
      <div className="flex items-baseline justify-between mb-2">
        <span className="font-semibold text-[15px]">Анкета заполнена</span>
        <span className="font-extrabold text-[17px]">{percent}%</span>
      </div>

      <div
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-1.5 rounded-full bg-surface-3 overflow-hidden mb-3"
      >
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${percent}%` }}
          transition={{ type: "spring", stiffness: 120, damping: 20 }}
          className="h-full rounded-full bg-accent"
        />
      </div>

      {/* Показываем два ближайших пункта, а не весь список: длинный перечень
          недостатков скорее отталкивает, чем мотивирует */}
      <p className="text-caption text-text-muted mb-3">
        Осталось: {missing.slice(0, 2).map((m) => m.label.toLowerCase()).join(", ")}
        {missing.length > 2 ? ` и ещё ${missing.length - 2}` : ""}
      </p>

      <Button variant="secondary" size="sm" onClick={onEdit}>
        <Pencil size={15} />
        Дозаполнить
      </Button>
    </Card>
  );
}

/** Точечный баннер, который просит заполнить одно конкретное поле.
 *
 * Общий «дозаполните анкету» работает слабо: читается как чужая просьба.
 * «У вас есть субкультура? Укажите её» — тёплый приём, потому что
 * упирается в одно поле, у которого есть короткая обратная связь (увидят
 * на анкете), а не в целый список на 8 пунктов. Рисуем баннером, а не
 * тостом: тост бы мигнул и исчез, а тут он ждёт решения.
 */
function ScreenChoice({
  label,
  hint,
  active,
  onPick,
}: {
  label: string;
  hint: string;
  active: boolean;
  onPick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onPick}
      aria-pressed={active}
      className={`flex-1 rounded-[var(--radius-tile)] border p-3.5 text-left
                 transition-colors ${
                   active
                     ? "border-accent bg-accent/10"
                     : "border-hairline bg-surface"
                 }`}
    >
      <div className="flex items-center justify-between mb-1.5">
        <span className="font-semibold text-[15px]">{label}</span>
        {active && <Check size={16} className="text-accent" />}
      </div>
      <p className="text-caption text-text-muted">{hint}</p>
    </button>
  );
}

function NudgeBanner({
  profile,
  onJump,
}: {
  profile: UserProfile | null;
  onJump: (field: string) => void;
}) {
  const [closedKey, setClosedKey] = useState<string | null>(
    localStorage.getItem("nudge_closed_key"),
  );

  // Порядок важен: «у вас есть субкультура» звучит интереснее, чем «заполните
  // рост», поэтому даже при равном весе его стоит ставить выше.
  const PRIORITY: {
    key: string;
    text: string;
    cta: string;
    done: (p: UserProfile) => boolean;
  }[] = [
    { key: "subculture", text: "У вас есть субкультура? Укажите свою, и другие увидят её в анкете", cta: "Указать субкультуру", done: (p) => !!p.subculture },
    { key: "mbti", text: "Есть результат MBTI? Его видно прямо на карточке", cta: "Указать MBTI", done: (p) => !!p.mbti },
    { key: "height", text: "Рост поднимает анкету в фильтрах у людей с ним", cta: "Указать рост", done: (p) => p.height_cm != null },
  ];

  const missing = PRIORITY.filter((i) => !i.done(profile!));

  // Полностью заполненный профиль не нуждается в баннере
  if (!profile || !missing.length) return null;
  if (closedKey === missing[0].key) return null;

  const current = missing[0];

  return (
    <Card className="p-4 mb-4 border-accent/25 bg-accent/8 relative">
      <button
        aria-label="Закрыть"
        onClick={() => {
          localStorage.setItem("nudge_closed_key", current.key);
          setClosedKey(current.key);
        }}
        className="absolute top-2.5 right-2.5 w-6 h-6 rounded-full
                   flex items-center justify-center text-text-muted
                   hover:bg-surface-2"
      >
        <X size={13} />
      </button>
      <div className="flex items-start gap-3 pr-6">
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-[15px] mb-1">{current.text}</p>
          <p className="text-caption text-text-muted">
            Это бесплатно и займёт 30 секунд
          </p>
        </div>
      </div>
      <Button
        size="sm"
        variant="secondary"
        onClick={() => onJump(current.key)}
        className="mt-3"
      >
        {current.cta}
      </Button>
    </Card>
  );
}

/* ── Мои ролики ─────────────────────────────────────────────── *//**
 * Свои ролики с пометкой о скрытых. Именно здесь автор узнаёт, что видео сняли
 * с показа: в общей ленте такого ролика нет, и без этого блока он решил бы,
 * что загрузка не сработала.
 */
function MyReelsCard() {
  const [reels, setReels] = useState<ReelType[] | null>(null);

  useEffect(() => {
    getMyReels()
      .then((page) => setReels(page.reels))
      .catch(() => setReels([])); // блок необязателен
  }, []);

  if (!reels?.length) return null;

  const hidden = reels.filter((r) => r.is_hidden).length;

  return (
    <Card className="p-4 mb-4">
      <div className="flex items-center gap-2.5 mb-3">
        <Film size={18} className="text-accent" />
        <span className="font-semibold text-[15px] flex-1">Мои видео</span>
        <Link
          to="/reels"
          onClick={() => haptic("light")}
          className="text-[13px] font-semibold text-accent"
        >
          В ленту
        </Link>
      </div>

      <div className="flex gap-2 overflow-x-auto no-scrollbar">
        {reels.map((reel) => (
          <div
            key={reel.id}
            className="relative w-[64px] h-[86px] shrink-0 rounded-[10px]
                       overflow-hidden bg-surface-2"
          >
            {reel.cover_url ? (
              <img
                src={reel.cover_url}
                alt=""
                loading="lazy"
                className={`w-full h-full object-cover ${
                  reel.is_hidden ? "opacity-40" : ""
                }`}
              />
            ) : (
              <span
                className="w-full h-full flex items-center justify-center"
                style={{ background: "var(--gradient-placeholder)" }}
              >
                <Film size={16} className="text-white/40" />
              </span>
            )}
            {reel.is_hidden && (
              <span className="absolute inset-0 flex items-center justify-center">
                <EyeOff size={16} className="text-warn" />
              </span>
            )}
          </div>
        ))}
      </div>

      {hidden > 0 && (
        <p className="text-caption text-warn mt-2.5">
          {hidden === 1 ? "Один ролик снят" : `${hidden} ролика сняты`} модерацией —
          в ленте их не видно
        </p>
      )}
    </Card>
  );
}
