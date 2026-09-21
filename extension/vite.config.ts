import { existsSync, readFileSync, writeFileSync } from "fs";
import { resolve } from "path";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type Plugin } from "vite";

function extraApiHostPlugin(apiBase: string): Plugin {
  return {
    name: "coursebrain-manifest-hosts",
    closeBundle() {
      const manifestPath = resolve(__dirname, "dist/manifest.json");
      if (!existsSync(manifestPath) || !apiBase) return;
      let extra: string;
      try {
        const url = new URL(apiBase);
        if (url.hostname === "localhost" || url.hostname === "127.0.0.1") return;
        extra = `${url.protocol}//${url.host}/*`;
      } catch {
        return;
      }
      const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
      const hosts: string[] = manifest.host_permissions ?? [];
      if (hosts.includes(extra)) return;
      hosts.push(extra);
      manifest.host_permissions = hosts;
      writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, "VITE_");
  return {
    base: "./",
    plugins: [react(), extraApiHostPlugin(env.VITE_API_BASE || "")],
    build: {
      outDir: "dist",
      emptyOutDir: true,
      rollupOptions: {
        input: {
          sidepanel: resolve(__dirname, "sidepanel.html"),
          background: resolve(__dirname, "src/background/service-worker.ts"),
        },
        output: {
          entryFileNames: (chunk) => {
            if (chunk.name === "background") return "background/service-worker.js";
            return "assets/[name]-[hash].js";
          },
        },
      },
    },
  };
});
