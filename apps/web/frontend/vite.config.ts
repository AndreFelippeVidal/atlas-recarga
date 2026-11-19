/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// As malhas do mapa ficam em apps/web/public/geo (geradas por scripts/fetch_geo.py). No dev o vite as
// serve pelo publicDir; no build elas não são copiadas: o FastAPI serve `public/geo` em `/geo`
// (SPEC-007 §2) e o build vai para apps/web/static, que é versionado (P12.8).
export default defineConfig(({ command }) => ({
  plugins: [react()],
  publicDir: command === "build" ? false : "../public",
  build: { outDir: "../static", emptyOutDir: true },
  server: { proxy: { "/api": "http://localhost:8000" } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
}));
