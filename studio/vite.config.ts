import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import manifest from "./package.json";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  define: { __PARALLAX_VERSION__: JSON.stringify(manifest.version) },
  base: "/",
  build: {
    outDir: ["hosted", "cloud"].includes(mode)
      ? "dist"
      : "../src/parallax/static",
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      treeshake: false,
      output: {
        onlyExplicitManualChunks: true,
        // Keep graph libraries separate and below the plugin directory file limit.
        // Public entry does not load the Studio/graph dependency tree.
        manualChunks(id) {
          if (/\/node_modules\/(?:@xyflow\/|d3-[^/]+\/|zustand\/)/.test(id))
            return "graph-vendor";
        },
      },
    },
  },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
}));
