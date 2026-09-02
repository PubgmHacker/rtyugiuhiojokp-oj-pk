/**
 * Схемы оформления и живой фон.
 *
 * Почему тесты: applyAppearance красит фон переменными на <html>, а не
 * через React, поэтому ошибка здесь не падает ни typecheck'ом, ни рендером —
 * орбы просто становятся прозрачными или остаются от прошлой схемы. Тумблер
 * «Живое движение» тоже живёт вне дерева React и виден только глазами.
 */

import { beforeEach, describe, expect, it } from "vitest";
import {
  APPEARANCES,
  appearanceByKey,
  applyAppearance,
  applyLivingMotion,
  initAppearance,
  loadLivingMotion,
} from "../appearance";

const root = () => document.documentElement;

beforeEach(() => {
  localStorage.clear();
  root().removeAttribute("data-appearance");
  root().removeAttribute("data-living");
  root().removeAttribute("data-motion");
  root().removeAttribute("style");
});

describe("палитра орбов", () => {
  it("у каждой схемы задана: три цвета у тёмных, null у светлых", () => {
    for (const a of APPEARANCES) {
      const светлая = a.key === "light" || a.key === "sepia";
      if (светлая) {
        expect(a.orbs, a.key).toBeNull();
      } else {
        expect(a.orbs, a.key).toHaveLength(3);
        for (const цвет of a.orbs!) expect(цвет).toMatch(/^#[0-9a-f]{6}$/);
      }
    }
  });

  it("первый орб — акцент схемы, как в Plink (accent, second, third)", () => {
    for (const a of APPEARANCES) {
      if (!a.orbs) continue;
      if (a.key === "graphite") {
        // «Графит» — исключение: его акцент почти белый (#d8d8dc), и орб такого
        // цвета на 42% выжег бы канву. Орбы серые — без оттенка, но темнее.
        for (const цвет of a.orbs) {
          const [r, g, b] = [1, 3, 5].map((i) => parseInt(цвет.slice(i, i + 2), 16));
          expect(Math.max(r, g, b) - Math.min(r, g, b), цвет).toBeLessThan(24);
        }
        continue;
      }
      expect(a.orbs[0], a.key).toBe(a.swatch[2]);
    }
  });
});

describe("applyAppearance красит фон", () => {
  it("ставит --orb-1…3 из палитры схемы", () => {
    applyAppearance("midnight");
    const [c1, c2, c3] = appearanceByKey("midnight").orbs!;
    expect(root().style.getPropertyValue("--orb-1")).toBe(c1);
    expect(root().style.getPropertyValue("--orb-2")).toBe(c2);
    expect(root().style.getPropertyValue("--orb-3")).toBe(c3);
    expect(root().hasAttribute("data-living")).toBe(false);
  });

  it("светлая схема выключает слой и убирает цвета прошлой", () => {
    applyAppearance("nebula");
    applyAppearance("light");
    expect(root().getAttribute("data-living")).toBe("off");
    expect(root().style.getPropertyValue("--orb-1")).toBe("");
    expect(root().style.getPropertyValue("--orb-3")).toBe("");
  });

  it("возврат к базовой схеме включает слой обратно", () => {
    applyAppearance("light");
    applyAppearance("nebula");
    expect(root().hasAttribute("data-appearance")).toBe(false);
    expect(root().hasAttribute("data-living")).toBe(false);
    expect(root().style.getPropertyValue("--orb-1")).toBe("#a855f7");
  });

  it("искра ставится только схемам, у которых она есть", () => {
    applyAppearance("nebula");
    expect(root().style.getPropertyValue("--spark")).toBe("#e6dcff");
    // Графит обещает «без цвета»: тёплой искры у него нет, и переменная
    // от прошлой схемы не должна пережить переключение.
    applyAppearance("graphite");
    expect(root().style.getPropertyValue("--spark")).toBe("");
    applyAppearance("dawn");
    applyAppearance("light");
    expect(root().style.getPropertyValue("--spark")).toBe("");
  });
});

describe("живое движение", () => {
  it("по умолчанию включено", () => {
    expect(loadLivingMotion()).toBe(true);
    initAppearance();
    expect(root().hasAttribute("data-motion")).toBe(false);
  });

  it("выключение замораживает орбы и переживает перезапуск", () => {
    applyLivingMotion(false);
    expect(root().getAttribute("data-motion")).toBe("still");
    expect(loadLivingMotion()).toBe(false);

    root().removeAttribute("data-motion");
    initAppearance();
    expect(root().getAttribute("data-motion")).toBe("still");

    applyLivingMotion(true);
    expect(root().hasAttribute("data-motion")).toBe(false);
    expect(loadLivingMotion()).toBe(true);
  });
});
