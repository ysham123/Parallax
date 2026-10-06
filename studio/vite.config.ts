import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  base: "/",
  build: {
    outDir: ["hosted", "cloud"].includes(mode)
      ? "dist"
      : "../src/parallax/static",
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: { treeshake: false },
  },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
}));
