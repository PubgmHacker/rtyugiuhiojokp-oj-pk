/**
 * Вход через Apple в нативной сборке iOS.
 *
 * App Store требует его там, где вход идёт через сторонний сервис
 * (Guideline 4.8) — для дейтинга это частая причина отклонения. В вебе и в
 * Telegram Mini App личность даёт initData, поэтому здесь всё под isNative().
 *
 * Токен наружу не проверяем: подпись проверяет сервер
 * (`api/services/apple_auth.py`). Тело JWT — обычный base64, и «проверка» в
 * приложении не даёт ничего.
 */

import { registerPlugin } from "@capacitor/core";
import { isNative } from "./native";
import api from "./api";
import type { UserProfile } from "./api";

interface AppleSignInResult {
  identityToken: string;
  /** Приходит ТОЛЬКО при первом входе и только если человек разрешил. */
  fullName: string;
  email: string;
}

interface AppleSignInPlugin {
  isAvailable(): Promise<{ available: boolean }>;
  signIn(): Promise<AppleSignInResult>;
}

const Плагин = registerPlugin<AppleSignInPlugin>("SouldawnAppleSignIn");

/** Отмена — не ошибка: человек сам закрыл окно. */
export class ВходОтменён extends Error {}

/** Доступен ли вход через Apple: только в нативной сборке. */
export async function appleSignInAvailable(): Promise<boolean> {
  if (!isNative()) return false;
  try {
    const { available } = await Плагин.isAvailable();
    return available;
  } catch {
    // Плагин не собран в этой сборке — кнопку просто не показываем
    return false;
  }
}

/**
 * Войти через Apple. Возвращает токен сессии и профиль.
 *
 * Имя передаём серверу как есть: Apple отдаёт его один раз, и если не
 * сохранить сейчас, при повторных входах его уже не будет.
 */
export async function signInWithApple(): Promise<{
  token: string;
  user: UserProfile;
}> {
  let результат: AppleSignInResult;
  try {
    результат = await Плагин.signIn();
  } catch (e: any) {
    if (String(e?.message ?? e).includes("canceled")) {
      throw new ВходОтменён("Вход отменён");
    }
    throw e;
  }

  const { data } = await api.post("/auth/apple", {
    identity_token: результат.identityToken,
    full_name: результат.fullName,
  });

  if (!data.success) throw new Error("Apple не подтвердил вход");
  return { token: data.token, user: data.user };
}
