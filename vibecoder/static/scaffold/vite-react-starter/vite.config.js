import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vibecoder serves this dev server through a reverse proxy that does not
// forward WebSocket traffic, so HMR's own socket is disabled here; the
// Vibecoder chat UI reloads the preview iframe after each edit instead.
// `base` is passed on the CLI (--base) by the Vibecoder project runner so
// every asset URL this server emits is prefixed with the proxy path.
export default defineConfig({
  plugins: [react()],
  server: {
    hmr: false,
  },
});
