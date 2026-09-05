import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";

/**
 * Два уговора, которые не ловит ни typecheck, ни глаз на ревью, потому что
 * нарушение выглядит как обычный код и всплывает только на скриншоте.
 *
 * Первый: карточка без внутреннего отступа. <Card> — это голое стекло со
 * скруглением, отступ задаёт вызывающий. Забыть его легко, и тогда текст
 * лежит вплотную к кромке — так и жила «Почта для входа» в профиле.
 *
 * Второй: эмодзи в интерфейсе. От них отказались осознанно — рисунок в
 * шрифте системы чужой любой схеме и тянет на себя больше внимания, чем
 * строка, рядом с которой стоит. Один вернувшийся эмодзи ломает ряд.
 */

const SRC = resolve(__dirname, "..");

function исходники(): string[] {
  const out: string[] = [];
  const обойти = (dir: string) => {
    for (const имя of readdirSync(dir)) {
      const p = join(dir, имя);
      if (statSync(p).isDirectory()) {
        if (имя !== "__tests__") обойти(p);
      } else if (/\.tsx?$/.test(имя) && !/\.test\.tsx?$/.test(имя)) {
        out.push(p);
      }
    }
  };
  обойти(SRC);
  return out;
}

const ФАЙЛЫ = исходники().map((p) => [relative(SRC, p), readFileSync(p, "utf8")] as const);

describe("уговоры вёрстки", () => {
  it("файлов набралось столько, что тест действительно что-то смотрит", () => {
    expect(ФАЙЛЫ.length).toBeGreaterThan(80);
  });

  it("у каждой <Card> есть свой внутренний отступ", () => {
    const голые: string[] = [];
    for (const [путь, текст] of ФАЙЛЫ) {
      for (const m of текст.matchAll(/<Card\b[^>]*>/g)) {
        // Открывающий тег, а не дженерик useState<Card | null>: у тега либо
        // есть атрибут со знаком «=», либо он голый — <Card>
        const тег = m[0] === "<Card>" || m[0].includes("=");
        if (!тег) continue;
        if (!/\bp-\[|\bp-\d|\bpx-|\bpy-|\bpt-|\bpb-/.test(m[0])) {
          голые.push(`${путь}: ${m[0].slice(0, 70)}`);
        }
      }
    }
    expect(голые).toEqual([]);
  });

  it("в интерфейсе нет эмодзи", () => {
    const найдено: string[] = [];
    const эмодзи = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}]/u;
    for (const [путь, текст] of ФАЙЛЫ) {
      текст.split("\n").forEach((строка, i) => {
        const m = строка.match(эмодзи);
        if (m) найдено.push(`${путь}:${i + 1} ${m[0]}`);
      });
    }
    expect(найдено).toEqual([]);
  });

  it("многоточие — знак «…», а не три точки", () => {
    const найдено: string[] = [];
    for (const [путь, текст] of ФАЙЛЫ) {
      for (const m of текст.matchAll(/"[^"\n]*\.\.\.[^"\n]*"/g)) {
        // ...rest / ...props — это раскрытие, а не текст
        if (!/\.\.\.[A-Za-zА-Яа-я_$]/.test(m[0])) найдено.push(`${путь}: ${m[0].slice(0, 60)}`);
      }
    }
    expect(найдено).toEqual([]);
  });
});
