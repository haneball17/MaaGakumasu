# Codex 与 HIF 录像处理能力调研

> 调研日期：2026-07-23。范围是当前 Codex Desktop 会话可调用能力，以及可选的官方接口 / MCP 扩展；不安装任何软件或配置。

## 结论

当前会话**不能直接把 MP4/MKV 当作视频交给 Agent 分析**：已启用的是本地静态图片查看（`view_image`）和图片生成 Skill，没有视频解码、音频转录或视频专用 MCP。HIF 录像仍可作为证据源，但要先在本地提取关键帧；音轨转录是可选补充，而非管线识别的前置条件。

最小可行流程是：保留原始录屏 → 按页面转场抽帧为 PNG/JPEG → 将关键帧交给 Codex 归类、标注 ROI 与状态迁移 → 再用 Maa 单步点击验证。不要据人工录像直接开放连续自动点击。

## 能力矩阵

| 类别 | 当前可用 | 适用 HIF 的工作 | 局限 | 推荐 |
| --- | --- | --- | --- | --- |
| 视频帧处理 | 否 | 无法在本会话直接解封装 MP4/MKV | 当前系统中未发现 `ffmpeg`、`yt-dlp` 或视频专用 Skill / MCP；项目依赖仅覆盖静态图片 | 外部/本机先用 FFmpeg 等解码器抽帧；保持原始文件与时间戳对应表 |
| 静态视觉理解 | 是 | 检查页面锚点、按钮、OCR 文本、ROI、人工操作前后状态 | 单张/少量帧不等于播放视频；无法证明点击后的 Maa 实机后态 | 每个关键动作保留“点击前、点击后、稳定页”三帧 |
| 音频转录 | 否（当前会话） | 将口述的页面、选择和结果转为检索文本 | 不是 HIF UI 识别证据；云 API 的格式/体积限制也可能要求先分段 | 仅在录像含清晰口述标注时使用；否则以画面帧和 Journal 为准 |
| MCP 扩展 | 当前无视频 MCP | 可由自建/已授权 MCP 暴露“抽帧、镜头切分、转录”等工具 | MCP 是工具连接协议，不自动提供媒体能力；接入会改变本地配置并需单独授权 | 暂不为一次录制安装。录像量稳定增加后，再选一个只读媒体 MCP |
| Codex Skill | 当前无视频专用 Skill | 可复用“抽帧→清单→人工复核”的流程 | Skill 本身不提供编解码器；仍依赖本机程序或 MCP | 先按现有 HIF 手动测试和证据文档流程执行，不新增 Skill |

## 官方资料与可核查事实

1. OpenAI 的图像与视觉指南将视觉输入定义为图像 URL 或 Base64 图像，支持 PNG、JPEG、WEBP 和非动画 GIF；该指南没有将通用视频文件列为视觉输入。它适合分析抽出的关键帧，而不是声明可直接理解录像文件。
   - 来源：[Images and vision | OpenAI API](https://developers.openai.com/api/docs/guides/images-vision#image-input-requirements)

2. OpenAI 的语音转文字接口支持常见音频容器（包括 `mp4`），但单个文件上限为 25 MB。该能力属于 API 集成；当前 Codex 会话未暴露转录工具，也不能把“API 可用”视为“本会话已可转录”。
   - 来源：[Speech to text | OpenAI API](https://developers.openai.com/api/docs/guides/speech-to-text#longer-inputs)

3. MCP 是把外部数据源和工具接入模型的开放协议。它可以承载媒体处理工具，但协议本身不规定视频解码或转录能力，因此必须实际安装并授权某个媒体服务器才会产生这些能力。
   - 来源：[Codex MCP supported features](https://learn.chatgpt.com/docs/extend/mcp#supported-mcp-features)

4. Codex 的官方文档把 MCP、Skills 和插件分别定位为工具连接、可复用工作流与能力打包；它们均是扩展机制，不表示某类媒体功能已随会话启用。
   - 来源：[Codex skills and plugins](https://learn.chatgpt.com/docs/skills-and-plugins)

5. Codex 的官方“附加文件”说明列出文档、演示文稿、电子表格、PDF、图片和数据导出，并未列出视频。因此不能据该能力断言 Codex 能直接按时间轴理解本地录像。
   - 来源：[Codex Projects — attach files](https://learn.chatgpt.com/docs/projects#attach-files)

## 当前会话核验

- 已启用 Skill 中只有 `imagegen` 面向位图创建/编辑；没有视频处理或转录 Skill。
- 可调用工具包含 `view_image`，但其参数是本地**图片**路径；没有视频读取、音频转录、FFmpeg 或媒体 MCP 工具。
- `ffmpeg`、`yt-dlp`、`whisper` 均不在当前 `PATH`。这只是本机环境的即时结论，不是 Codex 产品功能限制。

## 对 HIF 的推荐边界

录像应被登记为页面证据：文件名、录制环境、视频时间戳、动作意图、前后帧和人工结果。它可以补齐 Pipeline 的页面分类、识别 ROI、候选与预期状态；它不能单独证明 Maa 点击坐标正确或点击后已抵达唯一安全状态。每一种将写入自动点击的动作，仍须按现有 HIF 单步测试流程在 MuMu 实机复核。

## 何时再扩展

当录像成为持续输入（例如每周多段、需要批量检索或口述转录）时，再评估：

1. 安装一个本地只读 FFmpeg 抽帧工具；或
2. 接入只暴露 `extract_frames` / `transcribe` 的最小 MCP。

在此之前，新增 MCP 或 Skill 的维护成本高于手工抽取关键帧的收益。
