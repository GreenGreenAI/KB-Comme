import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // The dev server talks to uvicorn so the browser sees one origin.
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
