import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

function stripCrossorigin(): Plugin {
  return {
    name: "strip-crossorigin",
    apply: "build",
    transformIndexHtml: {
      order: "post",
      handler(html) {
        return html.replaceAll(" crossorigin", "");
      },
    },
  };
}

export default defineConfig({
  plugins: [react(), stripCrossorigin()],
  base: "./",
  server: { host: "127.0.0.1", port: 43124, strictPort: true },
});
