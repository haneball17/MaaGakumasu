# MaaFramework 官方文档本地镜像

本目录是 MaaFramework 官方中文文档的只读镜像，供 AI 代理与开发者离线查阅，避免反复联网和文档漂移。

## 来源

- 仓库：https://github.com/MaaXYZ/MaaFramework
- 目录：`docs/zh_cn/`
- 抓取方式：`git clone --depth 1 --filter=blob:none --sparse` + `git sparse-checkout set docs/zh_cn`
- 官方 commit：`2bf1ae6aa76689af6ebc8fdc8ee0234dd2a61345`（`chore: autopublish Sat Aug 8 23:08:42 UTC 2026`）
- 本地抓取日期：2026-08-09

## 文档清单与用途

| 文件 | 用途 |
|---|---|
| `1.1-快速开始.md` | 入门 |
| `1.2-术语解释.md` | Pipeline / ROI / resource 等概念 |
| `1.3-Custom&Agent.md` | Custom recognition / action 通用说明 |
| `2.1-集成文档.md` / `2.2-集成接口一览.md` | Context API、Tasker/Resource/Controller 接口 |
| `2.3-回调协议.md` | 回调消息协议 |
| `2.4-控制方式说明.md` | ADB / Win32 等控制器 |
| `3.1-任务流水线协议.md` | **核心**：Pipeline 协议 + 所有 recognition/action 类型与默认值 |
| `3.3-ProjectInterfaceV2协议.md` | **核心**：interface.json 任务配置协议 v2（本项目 `assets/interface.json` 使用） |
| `NodeJS/J1.2-自定义识别_操作.md` | Node.js 下 Custom 绑定（Python 侧方法名类似，可对照） |

## 维护规则

- 这是**只读镜像**，不要直接编辑这里的 `.md`；项目自有开发约定写在根目录 `AGENTS.md` 和 `docs/zh_cn/`。
- MaaFramework 版本更新后需刷新：重新执行 sparse clone，更新本文件的 commit 与日期。
- 若发现镜像与实际 MaaFramework 行为不符，以实际行为为准并在 `AGENTS.md` 注明。
