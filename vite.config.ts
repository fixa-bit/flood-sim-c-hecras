import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import cesium from "vite-plugin-cesium";

export default defineConfig({
  plugins: [react(), cesium({ devMinifyCesium: true })],
  server: {
    port: 5174,
    strictPort: true,
    watch: {
      ignored: [
        "**/.venv/**",
        "**/workspace/**",
        "**/test-results/**",
        "**/playwright-report/**",
      ],
    },
    proxy: {
      "/api": "http://127.0.0.1:8010",
      "/outputs": "http://127.0.0.1:8010",
    },
  },
});
