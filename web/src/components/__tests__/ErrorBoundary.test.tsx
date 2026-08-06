/**
 * Белый экран без объяснения и без выхода — худший сценарий отказа: человек не
 * понимает, сломался он или приложение, и просто уходит. Проверяем, что
 * исключение при рендере превращается в понятный экран с кнопкой.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import ErrorBoundary from "../ErrorBoundary";

function Ломается(): React.ReactElement {
  throw new Error("тестовая поломка");
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ErrorBoundary", () => {
  it("показывает экран с выходом вместо белого экрана", () => {
    // React печатает ошибку в консоль — заглушаем, чтобы вывод теста читался
    vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <ErrorBoundary>
        <Ломается />
      </ErrorBoundary>
    );

    expect(screen.getByText("Что-то сломалось")).toBeInTheDocument();
    // Кнопка обязательна: без неё человек всё равно в тупике
    expect(screen.getByRole("button", { name: "Обновить" })).toBeInTheDocument();
  });

  it("не мешает обычному рендеру", () => {
    render(
      <ErrorBoundary>
        <p>всё хорошо</p>
      </ErrorBoundary>
    );

    expect(screen.getByText("всё хорошо")).toBeInTheDocument();
    expect(screen.queryByText("Что-то сломалось")).not.toBeInTheDocument();
  });
});
