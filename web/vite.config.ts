import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built files are served by the Python server (src/secondscreen/server/static).
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../src/secondscreen/server/static", emptyOutDir: true },
  server: {
    proxy: {
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
      "/api": "http://127.0.0.1:8000",
    },
  },
});
