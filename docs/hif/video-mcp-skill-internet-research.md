# HIF 录像处理 MCP / Skill 互联网调研

> 调研日期：2026-07-23。范围：将本地 HIF 手工录像转成可核查的关键帧、文字与页面流转证据；不安装软件、不变更 MCP 配置。

## 结论

存在可直接服务 HIF 的候选。首选是 [`guimatheus92/mcp-video-analyzer`](https://github.com/guimatheus92/mcp-video-analyzer)：它的官方 README 明确支持本地绝对路径视频、场景变化关键帧或 1 fps 密集采样、每帧 OCR、Whisper 转录及带时间戳的聚合时间线。该组合正好覆盖“找页面转场 → 读 UI 文案 → 回溯人工操作”的离线证据工作。

建议先以一次**非特权、仅对指定录像目录的 CLI 试跑**验证效果；没有必要为 HIF 另行开发视频 MCP。它不是自动点击证据：得到的帧、OCR 和时间戳仍须映射到 Pipeline 节点，再以 Maa 单步实机验证点击目标和后态。

## 候选对比

| 顺序 | 项目与能力 | 维护信号（调研时） | HIF 结论 |
| --- | --- | --- | --- |
| 1 | [`mcp-video-analyzer`](https://github.com/guimatheus92/mcp-video-analyzer)：`get_frames`（场景变化或密集）、`get_frame_at`/burst、OCR、`get_transcript`、`analyze_video` 时间线；README 明确列出 local file。 | GitHub API：27 stars、7 forks、2026-07-21 有 push、MIT、未归档；[skills.sh 的 `video` Skill](https://www.skills.sh/guimatheus92/mcp-video-analyzer/video) 为 24 installs、26 GitHub stars，收录仅 12 天。活跃但非常新，不能把安装量当成熟度证明。 | **推荐试用。** 功能覆盖最完整，且本地录像不需要上传或 API key。 |
| 2 | [`video-creator/ffmpeg-mcp`](https://github.com/video-creator/ffmpeg-mcp)：README 的 `extract_frames_from_video` 可按秒/全部帧提取，另有视频信息和剪辑。 | GitHub API：140 stars、24 forks、最后 push 为 2026-05-20、MIT、未归档；README 声明“currently, only macOS”。 | **不推荐本 Windows 工作站。** 它只解决抽帧，且缺 OCR/转录/场景切分，兼容性也不合格。 |
| 3 | [NVIDIA Video Search and Summarization](https://docs.nvidia.com/vss/latest/)：官方 VSS 文档描述其视频摄取、分析和检索栈。 | 官方产品文档，非小型个人 MCP；部署为 GPU/容器化服务。 | **不用于当前任务。** HIF 离线录屏分析不需要多服务/GPU 检索系统；只有要对大量长录像做语义检索时再评估。 |

## 首选候选的安装与运行前提

来源：项目 [README](https://github.com/guimatheus92/mcp-video-analyzer/blob/main/README.md) 与其 [Skill 页面](https://www.skills.sh/guimatheus92/mcp-video-analyzer/video)。

- MCP：Node.js 18+，通过 `npx mcp-video-analyzer@latest` 启动 stdio server；本地文件必须传绝对路径或 `file://` URI。
- Skill：`npx skills add https://github.com/guimatheus92/mcp-video-analyzer --skill video`；skills.sh 当前记录 24 installs。该 Skill 在没有 MCP 时会调用同一个一次性 CLI，因此 **Skill 不是独立的视频引擎**。
- 帧：项目打包 `ffmpeg-static`，本地视频抽帧不需要系统 ffmpeg；`get_frames` 支持场景切分，`dense: true` 为 1 fps。
- OCR：使用项目依赖的 `tesseract.js`；失败会保留帧并在 warning 中报告。
- 转录：有同目录 `.vtt/.srt` 或内嵌字幕时可直接复用；否则需要安装 `openai-whisper`/兼容 CLI、配置可选 Hugging Face 模型，或提供 `OPENAI_API_KEY`。无后端会返回空转录和 warning，不应将其误判为“视频无语音”。
- 网络平台 URL 另需 `yt-dlp`；HIF 应传本地录屏，故不需要该依赖，也不应导出浏览器 cookies。

## 安全边界与最小试用方式

1. 只把手工录屏放到一个专用、非敏感目录；工具的 README 明确警告：任何可调用 MCP 的客户端都能要求进程读取它有权限的任意文件。不要把服务器进程放在能读取凭据、SSH key 或整个用户目录的权限边界内。
2. 首次不要启用 `MCP_WRITE_SIDECARS=1`：它会在视频旁写入 `.analysis.json`、`.frames/` 和可能的 `.vtt`。验证成功并确认这些衍生文件可接受后再启用可恢复批处理。
3. 不配置 `YTDLP_COOKIES` 或 `YTDLP_COOKIES_FROM_BROWSER`；HIF 本地视频无需 cookie。若未来使用 OpenAI Whisper API，API key 仅以进程环境变量提供，不写入仓库或 MCP 配置。
4. 对每个候选，先读固定版本的源码/lockfile，再使用固定版本而非 `@latest`；当前项目新、skills.sh 安装基数低，即使其页面显示多项安全审计通过，也不足以替代本地代码审查与最小权限运行。

## HIF 实际用法（拟议，不在本次执行）

对单个录像先取场景关键帧，再对包含快速点击、选项弹窗或页面淡入淡出的时间段取 burst；将输出按“时间戳 → 页面锚点/OCR → 人工选择 → 可见后态”登记到 HIF 页面证据。只有已确认唯一目标和后态的条目才可推动 Pipeline 动作；无法从录屏确定的触点维持观测或单步实机验证。

## 原始资料

- `mcp-video-analyzer`：[官方 README](https://github.com/guimatheus92/mcp-video-analyzer/blob/main/README.md)、[GitHub repository metadata API](https://api.github.com/repos/guimatheus92/mcp-video-analyzer)、[skills.sh Skill](https://www.skills.sh/guimatheus92/mcp-video-analyzer/video)。
- `ffmpeg-mcp`：[官方 README](https://github.com/video-creator/ffmpeg-mcp/blob/main/README.md)、[GitHub repository metadata API](https://api.github.com/repos/video-creator/ffmpeg-mcp)。
- NVIDIA VSS：[官方文档](https://docs.nvidia.com/vss/latest/)。
