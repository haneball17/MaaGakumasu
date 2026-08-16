# Round 模拟器本地 Web UI 技术栈

为 Round 模拟器（`docs/hif/roundsim-design.md` §8）引入 Vue 3 + Vite + ECharts 前端、FastAPI/uvicorn 本地服务与 node 构建链（新 Python 依赖 fastapi/uvicorn；此前仓库 Node 侧仅 prettier 工具链）。决策动机：模拟器需要「前端配置 → 触发模拟 → 看结果」的驱动体验与回放/分布可视化，纯 Python 生成 HTML（现有 `decisions/viewer.py` 模式）交互上限不足；本地工具定位不需要部署，FastAPI + 浏览器 localhost 是最轻的双向通信路径。

## Considered Options

- **纯 Python 自包含 HTML**（现有 viewer.py 模式，放弃）：零依赖可跑，但 scrubber 回放/图表/表单的交互复杂度超出原生 JS 合理维护范围。
- **桌面应用（Electron/Tauri）**（放弃）：打包与维护成本远超本地工具需要。
- **pyodide 浏览器内跑 Python 内核**（放弃）：蒙特卡洛在 WASM 下性能折损，依赖链不可控。
- **Vue 3**（选定）对比 Svelte 5 / React：Vue 上手最快、SFC 结构清晰、ECharts（Apache，中文文档一流）覆盖直方图/箱线图需求、训练语料最丰富；Svelte 5 bundle 更小但生态较小，React 对此场景过重（2026-08 调研，来源见 roundsim-design §12）。

## Consequences

- node（≥22 LTS）成为 UI 开发的前置环境；发布产物用 vite-plugin-singlefile 内联为自包含单 HTML，Python 注入 trace 后离线双击可开——不装 node 的使用者仍可查看已跑 trace（降级只读模式）。
- ScenarioSpec 以 Python pydantic 为单一真源导出 JSON Schema，前端 TS 类型对齐 + 契约测试锁定，防止双端漂移。
