import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/** 仅提供 React 开发与打包；没有官网代理或外部数据访问。 */
export default defineConfig({
  plugins: [react()],
  server: { strictPort: true },
  preview: { strictPort: true },
});
