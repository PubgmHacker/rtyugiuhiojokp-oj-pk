import { useState } from "react";
import { Mail, Check } from "lucide-react";
import { attachEmail, confirmEmail } from "../lib/api";
import { haptic } from "../lib/haptics";
import { Button, Card } from "./ui";

/**
 * Привязка почты — единственный способ вернуть аккаунт, если потерян Telegram.
 * Вместе с ним теряется и оплаченная подписка, а доказать, что аккаунт твой,
 * человеку нечем.
 *
 * Два шага, потому что непроверенная почта хуже, чем никакой: ошибся в букве —
 * и восстановление однажды уведёт аккаунт постороннему.
 */
export default function EmailRecovery({
  email,
  onAttached,
}: {
  email?: string | null;
  onAttached: (email: string) => void;
}) {
  const [открыто, setОткрыто] = useState(false);
  const [адрес, setАдрес] = useState("");
  const [код, setКод] = useState("");
  const [ждёмКод, setЖдёмКод] = useState(false);
  const [занято, setЗанято] = useState(false);
  const [ошибка, setОшибка] = useState("");

  const запросить = async () => {
    setЗанято(true);
    setОшибка("");
    try {
      await attachEmail(адрес.trim());
      setЖдёмКод(true);
      haptic("success");
    } catch (e: any) {
      setОшибка(e?.response?.data?.detail ?? "Не удалось отправить письмо");
      haptic("error");
    } finally {
      setЗанято(false);
    }
  };

  const подтвердить = async () => {
    setЗанято(true);
    setОшибка("");
    try {
      const { email: привязанная } = await confirmEmail(адрес.trim(), код.trim());
      onAttached(привязанная);
      setОткрыто(false);
      setЖдёмКод(false);
      setКод("");
      haptic("success");
    } catch (e: any) {
      setОшибка(e?.response?.data?.detail ?? "Код неверный или устарел");
      haptic("error");
    } finally {
      setЗанято(false);
    }
  };

  if (email) {
    return (
      <Card className="p-4 mb-4">
        <div className="flex items-center gap-3">
          <Check size={17} className="text-[#4ade80] shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-[14px] font-semibold">Почта привязана</p>
            <p className="text-[13px] text-text-muted truncate">{email}</p>
          </div>
        </div>
        <p className="mt-2 text-[12.5px] text-text-muted leading-relaxed">
          Если потеряете доступ к Telegram, войдёте по ней — вместе с подпиской.
        </p>
      </Card>
    );
  }

  return (
    <Card className="p-4 mb-4">
      <div className="flex items-center gap-3 mb-1">
        <Mail size={17} className="text-accent shrink-0" />
        <p className="text-[14px] font-semibold flex-1">Почта для входа</p>
      </div>
      <p className="text-[12.5px] text-text-muted leading-relaxed mb-3">
        Сейчас аккаунт держится только на Telegram. Потеряете его — потеряете
        анкету и оплаченную подписку. Почта нужна, чтобы вернуться.
      </p>

      {!открыто ? (
        <Button variant="secondary" size="sm" fullWidth onClick={() => setОткрыто(true)}>
          Привязать почту
        </Button>
      ) : (
        <div className="flex flex-col gap-2">
          <input
            type="email"
            inputMode="email"
            autoComplete="email"
            value={адрес}
            onChange={(e) => setАдрес(e.target.value)}
            placeholder="почта@пример.ru"
            disabled={ждёмКод}
            className="field w-full px-3.5 py-2.5 rounded-[var(--radius-control)] text-[14px] disabled:opacity-60"
          />

          {ждёмКод && (
            <>
              <p className="text-[12.5px] text-text-muted">
                Отправили код на {адрес}. Он действует 15 минут.
              </p>
              <input
                inputMode="numeric"
                autoComplete="one-time-code"
                value={код}
                onChange={(e) => setКод(e.target.value.replace(/\D/g, "").slice(0, 6))}
                placeholder="000000"
                className="field w-full px-3.5 py-2.5 rounded-[var(--radius-control)] text-[18px] tracking-[0.3em] text-center"
              />
            </>
          )}

          {ошибка && <p className="text-[12.5px] text-danger">{ошибка}</p>}

          <Button
            size="sm"
            fullWidth
            loading={занято}
            disabled={ждёмКод ? код.length < 6 : !адрес.includes("@")}
            onClick={ждёмКод ? подтвердить : запросить}
          >
            {ждёмКод ? "Подтвердить" : "Получить код"}
          </Button>
        </div>
      )}
    </Card>
  );
}
