/**
 * Раздача `dist` обязана отдавать юридические документы, а не SPA-оболочку.
 *
 * Беда, найденная на живом вебе: `https://<web>/terms.html` отвечал 301 на
 * `/terms`, а `/terms` — уже не документом, а `index.html` (10891 байт,
 * ровно оболочка мини-аппа). Причина — `cleanUrls` в `serve`: по умолчанию
 * он срезает `.html` редиректом, а дальше путь без расширения попадает под
 * SPA-фолбэк `-s` и превращается в оболочку. Итог: человек, которого просят
 * принять оферту, открывает свою же деку. То же самое ломало ссылки из бота
 * (`bot/config.py: legal_url`) и `web/src/lib/legal.ts` — все они адресуют
 * документы именно как `<page>.html`.
 *
 * Лечится не кодом, а конфигом раздачи: `serve.json` с `cleanUrls: false`
 * лежит в `web/public`, откуда Vite копирует его в `dist` рядом с
 * документами — `serve` читает конфиг из корня раздаваемой папки. Проверено
 * вживую на локальном `serve dist -s`: с конфигом `/terms.html` = 22226
 * байт документа, `/discover` и `/login` по-прежнему отдают оболочку,
 * `/assets/*` и `/manifest.json` — свои файлы.
 *
 * Тест держит именно этот контракт: без него правка `serve.json` или возврат
 * дефолта снова уводит оферту в SPA, и заметно это только на проде.
 */

import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

import { ДОКУМЕНТЫ, АССЕТЫ } from "../sync-landing.mjs";

const КОРЕНЬ = path.resolve(import.meta.dirname, "..", "..");
const ПУБЛИЧНОЕ = path.join(КОРЕНЬ, "public");
const КОНФИГ = path.join(ПУБЛИЧНОЕ, "serve.json");

function конфиг() {
  return JSON.parse(fs.readFileSync(КОНФИГ, "utf8"));
}

describe("конфиг раздачи dist", () => {
  it("serve.json лежит в public — только оттуда он попадёт в dist", () => {
    expect(
      fs.existsSync(КОНФИГ),
      "без web/public/serve.json конфига в dist не будет: serve читает его из " +
        "корня раздаваемой папки, а public — единственное дерево, которое Vite " +
        "копирует туда как есть"
    ).toBe(true);
  });

  it("cleanUrls выключен — иначе .html уводит документ в SPA-фолбэк", () => {
    expect(
      конфиг().cleanUrls,
      "cleanUrls:true (дефолт serve) редиректит /terms.html → /terms, а путь " +
        "без расширения забирает SPA-фолбэк -s и отдаёт index.html вместо оферты"
    ).toBe(false);
  });

  it("trailingSlash не добавляет слеш к именам файлов", () => {
    expect(конфиг().trailingSlash).toBe(false);
  });

  it("каждый юридический документ и его оформление реально лежат в public", () => {
    // Конфиг спасает от подмены оболочкой, но не от отсутствия самого файла:
    // тогда SPA-фолбэк снова отдаст index.html, уже законно.
    for (const имя of [...ДОКУМЕНТЫ, ...АССЕТЫ]) {
      const цель = path.join(ПУБЛИЧНОЕ, имя);
      expect(fs.existsSync(цель), `нет web/public/${имя} — путь отдаст оболочку`).toBe(true);
    }
  });

  it("старт раздачи по-прежнему serve dist -s: конфиг относится именно к нему", () => {
    const railway = JSON.parse(fs.readFileSync(path.join(КОРЕНЬ, "railway.json"), "utf8"));
    const старт = railway.deploy?.startCommand ?? "";
    expect(старт).toMatch(/serve\s+dist/);
    expect(
      старт,
      "SPA-фолбэк -s и есть причина, по которой cleanUrls опасен: пропал флаг " +
        "— тест ниже перестал бы охранять реальное поведение"
    ).toMatch(/\s-s\b/);

    const dockerfile = fs.readFileSync(path.join(КОРЕНЬ, "Dockerfile"), "utf8");
    expect(dockerfile).toMatch(/serve\s+dist\s+-s/);
  });
});
