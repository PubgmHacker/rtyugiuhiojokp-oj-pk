import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Отдельный конфиг, а не общий с vite.config.ts: тестам не нужен
// tailwindcss-плагин и ручные чанки продовой сборки.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/setupTests.ts"],
  },
});
