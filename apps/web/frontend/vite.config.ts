/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// As malhas do mapa ficam em apps/web/public/geo (geradas por scripts/fetch_geo.py).
export default defineConfig({
  plugins: [react()],
  publicDir: "../public",
  server: { proxy: { "/api": "http://localhost:8000" } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
