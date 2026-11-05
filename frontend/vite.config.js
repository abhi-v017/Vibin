import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development, forward /api requests to the FastAPI server so the browser
// sees one origin (no CORS headaches).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000" } },
});
