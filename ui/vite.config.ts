import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { viteSingleFile } from "vite-plugin-singlefile";

// 本地工具定位(ADR-0002):构建产物内联为自包含单 HTML,
// tools/render_round_ui.py 注入 __TRACE_DATA__ 后离线双击可开。
export default defineConfig({
    plugins: [vue(), viteSingleFile()],
    server: {
        port: 5273,
        proxy: {
            "/api": "http://127.0.0.1:8642",
        },
    },
});
