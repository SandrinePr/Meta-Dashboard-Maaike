import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const root = path.dirname(fileURLToPath(import.meta.url));
const certFile = path.resolve(root, "../data/local-https/cert.pem");
const keyFile = path.resolve(root, "../data/local-https/key.pem");
const https =
  fs.existsSync(certFile) && fs.existsSync(keyFile)
    ? { cert: fs.readFileSync(certFile), key: fs.readFileSync(keyFile) }
    : undefined;

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    https,
  },
  preview: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    https,
  },
});
