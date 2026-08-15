import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Local development: `npm run dev` proxies API calls to the compose API
// service (bound to 127.0.0.1:8000 by default).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/healthz": "http://localhost:8000",
    },
  },
});
