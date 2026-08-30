import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Builds to dist/ which docker-compose.override.yml's nginx service mounts
// at /usr/share/nginx/frontend (see infra/nginx/nginx.conf's `root`). The
// dev-server proxy lets `npm run dev` hit the real gateway without CORS.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
