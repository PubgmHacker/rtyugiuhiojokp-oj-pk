import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * Последний рубеж: исключение при рендере не должно оставлять белый экран.
 *
 * Без этого любая ошибка в любом компоненте роняла всё приложение целиком, и
 * человек видел пустоту — без объяснения и без способа выбраться. Перезагрузка
 * помогает в большинстве случаев, но догадаться до неё он должен сам.
 *
 * Классовый компонент, потому что ловить ошибки рендера умеет только
 * `componentDidCatch` — хуками это не делается.
 */
export default class ErrorBoundary extends Component<
  { children: ReactNode },
  { сломалось: boolean }
> {
  state = { сломалось: false };

  static getDerivedStateFromError() {
    return { сломалось: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // В консоль — чтобы в отладке было видно место, а не только следствие
    console.error("Ошибка рендера:", error, info.componentStack);
  }

  render() {
    if (!this.state.сломалось) return this.props.children;

    return (
      <div className="h-screen-safe flex flex-col items-center justify-center px-8 text-center gap-4">
        <div className="text-[52px] leading-none">🌅</div>
        <h1 className="text-[19px] font-bold">Что-то сломалось</h1>
        <p className="text-[14px] text-text-muted max-w-[34ch] leading-relaxed">
          Это на нашей стороне, а не у вас. Обновите приложение — обычно этого
          достаточно.
        </p>
        <button
          onClick={() => window.location.reload()}
          className="mt-1 h-12 px-6 rounded-[var(--radius-control)] bg-accent
                     text-white text-[15px] font-semibold"
        >
          Обновить
        </button>
      </div>
    );
  }
}
