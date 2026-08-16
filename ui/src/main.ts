import { createApp } from "vue";
import App from "./App.vue";

// 离线降级:render_round_ui.py 注入的 trace(无后端时回放视图仍可用)。
// 注意传值而非 ref——根 props 不做 ref 解包,ref 对象恒真会误判离线模式。
const injected = (window as unknown as { __TRACE_DATA__: unknown }).__TRACE_DATA__ ?? null;

createApp(App, { offlineTrace: injected }).mount("#app");
