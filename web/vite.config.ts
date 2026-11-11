import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The Python server (scenic-dmp serve) listens on 8765. In dev, Vite serves the
// app with hot reload and proxies the API and WebSocket to it.
const SERVER = process.env.SCENIC_DMP_SERVER ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "../src/scenic_dmp/web_dist", emptyOutDir: true, chunkSizeWarningLimit: 1500 },
  server: {
    proxy: {
      "/api": SERVER,
      "/ws": { target: SERVER.replace(/^http/, "ws"), ws: true },
    },
  },
});
