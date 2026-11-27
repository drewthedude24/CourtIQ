import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": process.env.COURTIQ_API_PROXY || "http://127.0.0.1:8000",
    },
  },
  // Two pages from one project: the original page at / and the new Studio page at /studio/.
  // To drop one later, delete its line here and its folder.
  build: {
    rollupOptions: {
      input: {
        main: "index.html",
        studio: "studio/index.html",
      },
    },
  },
});
