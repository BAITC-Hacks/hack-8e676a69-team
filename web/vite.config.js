import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Proxying both /api and /files means the frontend uses relative URLs
// identically in dev and prod, so there is no API base-URL env var anywhere.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/files": "http://127.0.0.1:8000",
    },
  },
});
