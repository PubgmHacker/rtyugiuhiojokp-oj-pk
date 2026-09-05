/**
 * Палитра личности и обложки.
 *
 * Почему тесты: цвет буквы и обложка считаются на клиенте из id и нигде не
 * хранятся. Разъехавшийся хеш незаметен ни typecheck'ом, ни рендером —
 * просто один и тот же человек станет разного цвета в Симпе и в Plink.
 * Держим байт-в-байт совпадение с FNV-1a iOS-клиента и коридор яркости,
 * без которого белая буква пропадает на светлых парах.
 */

import { describe, expect, it } from "vitest";
import {
  IDENTITY_PAIRS,
  auraAt,
  auraOf,
  identityIndex,
  legible,
  letterAvatarStyle,
  letterAvatarStyleAt,
  luminance,
  spreadIdentityIndexes,
  хеш,
} from "../aura";
import { COVER_PRESETS, coverBackground, coverForProfile } from "../cover";

describe("хеш FNV-1a", () => {
  it("совпадает с эталоном FNV-1a 32 бит", () => {
    // Канонические значения FNV-1a 32: пустая строка и «a»
    expect(хеш("")).toBe(0x811c9dc5);
    expect(хеш("a")).toBe(0xe40c292c);
  });

  it("не зависит от регистра и пробелов по краям — как в Plink", () => {
    expect(хеш("  User-42 ")).toBe(хеш("user-42"));
  });

  it("считает по байтам UTF-8, а не по кодовым единицам", () => {
    // «я» = D1 8F: хеш по двум байтам отличается от хеша по одной единице
    let h = 0x811c9dc5;
    for (const b of [0xd1, 0x8f]) {
      h ^= b;
      h = Math.imul(h, 0x01000193);
    }
    expect(хеш("я")).toBe(h >>> 0);
  });
});

describe("палитра личности", () => {
  it("восемь пар, индекс всегда в диапазоне", () => {
    expect(IDENTITY_PAIRS).toHaveLength(8);
    for (let i = 0; i < 200; i++) {
      const idx = identityIndex(`u-${i}`);
      expect(idx).toBeGreaterThanOrEqual(0);
      expect(idx).toBeLessThan(8);
    }
  });

  it("разные люди получают разные пары, один человек — одну", () => {
    const seen = new Set<number>();
    for (let i = 0; i < 64; i++) seen.add(identityIndex(`user-${i}`));
    expect(seen.size).toBe(8);
    expect(auraOf("abc")).toBe(auraOf("abc"));
    expect(auraOf("abc").pair).toEqual(IDENTITY_PAIRS[identityIndex("abc")]);
  });

  it("буква стоит на фоне с яркостью в коридоре 0.14–0.31", () => {
    for (const [a, b] of IDENTITY_PAIRS) {
      for (const c of [a, b]) {
        const L = luminance(legible(c));
        expect(L).toBeGreaterThanOrEqual(0.135);
        expect(L).toBeLessThanOrEqual(0.315);
      }
    }
    // Слишком тёмный подтягивается, слишком светлый притемняется
    expect(luminance(legible("#000000"))).toBeGreaterThan(0.13);
    expect(luminance(legible("#ffffff"))).toBeLessThan(0.32);
  });

  it("стиль заглушки — градиент пары и белая буква", () => {
    const s = letterAvatarStyle("u-1");
    expect(s.color).toBe("#ffffff");
    expect(s.background).toMatch(/^linear-gradient\(145deg, #[0-9a-f]{6}, #[0-9a-f]{6}\)$/i);
    expect(letterAvatarStyle(undefined).background).toBe(letterAvatarStyle("simp").background);
  });
});

describe("раздача палитры по списку", () => {
  // Восемь пар на восемь мест: короткий каталог, который человек видит
  // целиком, не должен показывать два одинаковых кружка подряд.
  const комнаты = ["smalltalk", "music", "games", "movies", "sport", "art"];

  it("auraAt берёт пару по индексу и совпадает с auraOf", () => {
    for (let i = 0; i < IDENTITY_PAIRS.length; i++) {
      expect(auraAt(i).pair).toEqual(IDENTITY_PAIRS[i]);
    }
    expect(auraAt(identityIndex("user-7"))).toBe(auraOf("user-7"));
  });

  it("индекс за границами заворачивается, включая отрицательный", () => {
    const n = IDENTITY_PAIRS.length;
    expect(auraAt(n)).toBe(auraAt(0));
    expect(auraAt(n + 3)).toBe(auraAt(3));
    expect(auraAt(-1)).toBe(auraAt(n - 1));
    expect(auraAt(-n - 2)).toBe(auraAt(n - 2));
  });

  it("шесть комнат получают шесть разных цветов", () => {
    // Ради этого всё и затевалось: сырой хеш давал три одинаковых оранжевых
    const сырые = комнаты.map(identityIndex);
    expect(new Set(сырые).size).toBeLessThan(комнаты.length);

    const розданные = spreadIdentityIndexes(комнаты);
    expect(розданные).toHaveLength(комнаты.length);
    expect(new Set(розданные).size).toBe(комнаты.length);
    for (const i of розданные) {
      expect(i).toBeGreaterThanOrEqual(0);
      expect(i).toBeLessThan(IDENTITY_PAIRS.length);
    }
  });

  it("первый в списке остаётся при своём цвете, раздача воспроизводима", () => {
    const розданные = spreadIdentityIndexes(комнаты);
    expect(розданные[0]).toBe(identityIndex(комнаты[0]));
    expect(spreadIdentityIndexes(комнаты)).toEqual(розданные);
    // Тот же набор в другом порядке — те же цвета у тех же строк
    const хвост = spreadIdentityIndexes(комнаты.slice(1));
    expect(хвост[0]).toBe(identityIndex(комнаты[1]));
  });

  it("список длиннее палитры не ломается — цвета начинают повторяться", () => {
    const много = Array.from({ length: 20 }, (_, i) => `room-${i}`);
    const розданные = spreadIdentityIndexes(много);
    expect(розданные).toHaveLength(20);
    for (const i of розданные) {
      expect(i).toBeGreaterThanOrEqual(0);
      expect(i).toBeLessThan(IDENTITY_PAIRS.length);
    }
    // Первые восемь всё ещё все разные
    expect(new Set(розданные.slice(0, IDENTITY_PAIRS.length)).size).toBe(IDENTITY_PAIRS.length);
    expect(spreadIdentityIndexes([])).toEqual([]);
  });

  it("letterAvatarStyleAt красит по индексу, буква белая", () => {
    for (let i = 0; i < IDENTITY_PAIRS.length; i++) {
      const s = letterAvatarStyleAt(i);
      expect(s.color).toBe("#ffffff");
      expect(s.background).toBe(auraAt(i).letter);
    }
    expect(letterAvatarStyleAt(identityIndex("u-1"))).toEqual(letterAvatarStyle("u-1"));
  });
});

describe("обложка анкеты", () => {
  it("рамка из кейсов даёт свой пресет, без рамки — цвета личности", () => {
    for (const code of ["dawn", "frost", "ember", "nebula", "eclipse"]) {
      expect(coverForProfile({ id: "x", decor: code })).toBe(COVER_PRESETS[code]);
    }
    const своя = coverForProfile({ id: "user-7", decor: null });
    expect(своя.accent).toBe(auraOf("user-7").accent);
    // Неизвестный код рамки не ломает лицо анкеты
    expect(coverForProfile({ id: "user-7", decor: "unknown" }).accent).toBe(своя.accent);
  });

  it("фон обложки — свечение поверх трёхстопного неба", () => {
    const css = coverBackground(COVER_PRESETS.nebula);
    expect(css).toMatch(/^radial-gradient\(circle at 85% 10%, rgb\(255 178 196 \/ 0\.55\)/);
    // пол — через color-mix с долей из темы: тёмные 100%, светлые снижают, чтобы низ не чернел
    expect(css).toContain(
      "linear-gradient(180deg, #5D4BD4 0%, #9A55C4 58%, color-mix(in srgb, #3A1E52 var(--cover-floor-mix, 100%), #9A55C4) 100%)"
    );
  });
});
