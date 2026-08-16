<!-- markdownlint-disable MD033 MD041 -->

<p align="center">
  <img alt="LOGO" src="./logo.png" width="256" height="256" />
</p>

<div align="center">

# MaaGakumasu

基于全新架构的 **学園アイドルマスター(学マス)** 小助手。图像技术 + 模拟控制 + 深度学习，解放双手！  
由 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 强力驱动！

如果 MaaGakumasu 对你有帮助，欢迎在项目右上角点亮 Star 支持。

</div>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white">
  <img alt="platform" src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-blueviolet">
  <img alt="CodeFactor" src="https://www.codefactor.io/repository/github/superwatergod/maagakumasu/badge">
  <img alt="Yolo" src="https://img.shields.io/badge/Yolo-v11-blue">
  <br>
  <img alt="license" src="https://img.shields.io/github/license/SuperWaterGod/MaaGakumasu">
  <img alt="commit" src="https://img.shields.io/github/commit-activity/m/SuperWaterGod/MaaGakumasu">
  <img alt="stars" src="https://img.shields.io/github/stars/SuperWaterGod/MaaGakumasu?style=social">
  <img alt="downloads" src="https://img.shields.io/github/downloads/SuperWaterGod/MaaGakumasu/total?style=social">
  <a href="https://mirrorchyan.com/zh/projects?rid=MaaGakumasu" target="_blank"><img alt="mirrorc" src="https://img.shields.io/badge/Mirror%E9%85%B1-%239af3f6?logo=countingworkspro&logoColor=4f46e5"></a>
</p>

## 功能概览

详细说明请查看 [功能说明](docs/zh_cn/功能说明.md)。当前 README 记录 `feat/hif` 分支开发状态；主线发布状态请同时参考 `assets/resource/Changelog.md`。

| 模块 | 当前支持 |
| --- | --- |
| 启动与日常 | 启动游戏、领取活动费、邮箱礼物、任务奖励、每周免费礼包 |
| 竞赛挑战 | 指定挑战、自动选择分差最小的对手、无编队时自动编队 |
| 社团互动 | 自动请求库存较少的物品，或按配置指定请求 |
| 安排工作 | 领取奖励、自动或指定偶像、指定工作时长 |
| 商店购买 | 扭蛋、金币、AP 购买，支持自动免费刷新 |
| 自动培育 | 初 `REGULAR/PRO/MASTER`，NIA `PRO/MASTER`，支持中断继续、初流程失败重试、老师建议、道具与卡片优先级；HIF 处于开发分支实验阶段 |
| 适配能力 | Mirror 酱更新、插件版汉化、DMM 版、支援卡库存识别、繁体 i18n |

### 自动培育

> [!IMPORTANT]
> 自动培育仍处于测试阶段。一次完整培育通常约 `30min`，可能产生大量日志，也可能因弹窗、识别样本不足或游戏 UI 变化而卡住。

当前自动培育支持：

- `初` 难度：`REGULAR`、`PRO`、`MASTER`
- `NIA` 难度：`PRO`、`MASTER`
- 指定偶像卡、自动选择偶像、跳过选择偶像
- 培育次数设置、手动输入次数、无限循环
- 使用体力药、使用道具、自动回忆、关注租借
- 中断后通过“跳过准备阶段”继续培育
- 卡片选择优先级：`建议卡 > 活动卡`、`活动卡 > 建议卡`、`无`
- 初流程考试失败自动重试
- 跟随老师的建议
- NIA 事件、镜像挑战、指导事件等自动选择逻辑
- `feat/hif` 分支已实机打通 HIF Day1→Round1 全链自动决策（Round1 到达后观察停止，暂不出牌）

### HIF 开发分支现状

> [!NOTE]
> 以下内容记录 `feat/hif` 分支截至 `2026-08-16` 的开发状态。HIF 相关能力仍处于开发与验证阶段，不代表主线稳定功能。

当前 `feat/hif` 分支已完成 HIF 从入口到 Round1 的实机自动决策闭环：

- 任务配置中已加入 `HIF` 培育难度与 `HIF预设`、`培育倾向`、`HIF 决策微调` 选项，入口跳转到 `ProduceEntryHIF`。
- `ProduceHIF.json` 作为 HIF Pipeline 状态机（约 37 节点），配合 `agent/custom/action/produce_hif.py` 的自定义动作覆盖日程、授業、P 道具、三选一（饮料/技能卡/変卡）、SP 卡、相談、饮料上限等页面。
- 三选一采用双评分：结构化评分模型 v2（官方公式对齐）优先，关键词评分兜底，支持重抽与名单优先；决策参数可经 GUI 选项、覆盖文件、培育倾向三层调整。
- 全决策点自动存档（截图 + JSONL），并提供 HTML 决策日志查看器与复盘总表脚本。
- HIF 出牌决策层 `agent/hif/decisions/` 已实现姫崎莉波 `ガラクタロード` 好调路线的再演压缩策略并通过离线测试，Round1 目前为“观察手牌后停止”模式，尚未接线实机出牌。
- 数据链已切换 gakumasu-diff 主干：121 张技能卡全表、效果池关联、社区 tier 榜抓取与评分校准（离线链 A/B 完成）。
- 当前测试覆盖约 128 个用例（决策全链、出牌策略、ExamState 适配、评分模型）。

当前仍未完成的关键工作：

- Round1 出牌执行接线、Round2、Interval、结算、メモリー（回忆卡）评分与整局自动培育；这些页面仍由 `ProduceHIFUnknownStop` 安全停止兜底。
- 评分模型 C2 人工调参与实机验证；快慢路径路由方案已定待实施。
- `ExamStateReader` 数值 ROI 部分字段仍待实机校准。
- `feat/hif` 分支相对当前 `origin/main` 存在主线提交差异，后续合并前需要处理同步与冲突。

后续建议优先级：

1. Round1 出牌接线与实机验证（`GarakutaRinamiStrategy` → `ProduceHIFRound1Observe` 升级为执行模式）。
2. 评分模型 C2 调参与快慢路径路由实施。
3. Round2/Interval/结算/メモリー页面覆盖。
4. 同步主线最新改动后再考虑合并或发布。

### 后续计划

- [ ] 初 `LEGEND` 培育适配
- [ ] HIF Round1 出牌接线与 Round2/Interval/结算覆盖
- [ ] HIF 评分模型调参、メモリー评分与整局自动培育
- [ ] 更多语言补充
- [ ] 更多自动培育样本覆盖

## 版本适配

| 环境 | 模拟器 | DMM |
| --- | --- | --- |
| 原版日语 | 已适配，已完全测试 | 已适配，已通过测试 |
| 插件版汉化 | 已适配，已通过测试 | 已适配，未完全测试 |

## 注意事项

> [!NOTE]  
> 项目主要在 Windows 与 MuMu 模拟器 12 上开发和测试。其他系统或模拟器若出现问题，请参考 [提问与反馈指南](docs/zh_cn/提问与反馈指南.md) 并优先保存 `debug\maa.log` 附带截图反馈。

1. 推荐使用 `MuMu 模拟器 12`，模拟器支持情况请查看 [MaaFramework 官方文档](https://maa.plus/docs/zh-cn/manual/device/windows.html)。
2. 推荐分辨率为 `1280x720 (240DPI)`；其他 `16:9` 分辨率和 DMM 端未做完整覆盖测试。
3. 使用 DMM 版时，需要以管理员身份启动程序。
4. 自动培育使用 `YOLOv11` 深度学习模型进行识别，请确保设备支持并启用 GPU 加速。
5. 培育前建议在游戏设置中开启所有跳过对话和弹窗选项，并勾选常见弹窗的“次回以降表示しない”。
6. 本项目仅用于学习交流，请勿用于商业用途。
7. 本项目仅提供自动化脚本，不提供任何游戏资源。

## 使用说明

### Windows

| 架构 | 下载文件 |
| --- | --- |
| 绝大多数 Windows 电脑 | `MaaGakumasu-win-x86_64-vXXX.zip` |
| Windows on ARM | `MaaGakumasu-win-aarch64-vXXX.zip` |

解压后运行 `MaaGakumasu.exe` 即可。压缩包已自带 `Python 3.12.9` 环境，无需额外安装。

首次启动会自动安装相关依赖。如果无法运行，请先安装 [`Visual C++ 可再发行程序包`](https://aka.ms/vs/17/release/vc_redist.x64.exe) 和 [`.NET 桌面运行时 10`](https://dotnet.microsoft.com/zh-cn/download/dotnet/10.0)，然后重启电脑。

Windows 10 或 11 用户也可以使用 `winget` 安装运行库：

```bash
winget install Microsoft.VCRedist.2015+.x64 Microsoft.DotNet.DesktopRuntime.10
```

### macOS

| 架构 | 下载文件 |
| --- | --- |
| Intel 处理器 | `MaaGakumasu-macos-x86_64-vXXX.zip` |
| Apple Silicon | `MaaGakumasu-macos-aarch64-vXXX.zip` |

压缩包已自带 `Python 3.12.9` 环境。解压后，在文件夹内打开终端并执行：

```bash
chmod a+x MFAAvalonia
chmod a+x python/bin/python3
./MFAAvalonia
```

若启动失败并提示缺少运行库，请按提示安装 `.NET` 运行库。若系统提示“Apple 无法检查其是否包含恶意软件”，请在“系统设置”中的“隐私与安全性”里选择“仍要打开”。由于文件较多，可能需要重复确认。

### Linux

Linux 版本提供基础包体，但当前主要测试仍集中在 Windows。遇到问题请携带日志反馈。

## 开发相关

MaaGakumasu 基于 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 开发，采用 `JSON + 自定义逻辑扩展` 模式。开发前建议先阅读：

- [功能说明](docs/zh_cn/功能说明.md)
- [开发相关](docs/zh_cn/开发相关.md)
- [提问与反馈指南](docs/zh_cn/提问与反馈指南.md)
- [MaaFramework 文档](https://maa.plus/docs/zh-cn/)

### YOLOv11 训练

YOLOv11 主要用于自动培育识别。模型训练参考 [MaaNeuralNetworkCookbook](https://github.com/MaaXYZ/MaaNeuralNetworkCookbook/tree/main/NeuralNetworkDetect)，数据集标注使用 [Roboflow](https://app.roboflow.com/gakumasu)。

| 数据集 | 用途 | 当前样本 |
| --- | --- | --- |
| `cards` | 出牌识别 | 约 902 份，已标注完成，并强化多卡重叠场景 |

> [!NOTE]
> 早期用于上课、冲刺选项识别的 `button` 数据集已废弃；相关按钮识别已改为普通模板匹配，不再使用 YOLOv11。

欢迎参与标注或提供样本，具体说明请查看 [开发相关](docs/zh_cn/开发相关.md)。

## Mirror 酱

自 `2025/11/08` 起，MaaGakumasu 已全面支持 Mirror 酱，在其他地方购买的 CDK 同样可以在此使用。

Mirror 酱是第三方应用分发平台，用于简化开源应用更新。用户付费使用，收益与开发者共享，Mirror 酱本身也是开源项目。

CDK 购买入口：[Mirror 酱官网](https://mirrorchyan.com/zh/projects?rid=MaaGakumasu)

## 免责声明

本软件开源、免费，仅供学习交流使用。若您遇到商家使用本软件进行代练并收费，可能是分发、设备或时间等费用，产生的费用、问题及后果与本软件无关。

**在使用过程中，MaaGakumasu 可能存在任何意想不到的问题，因 MaaGakumasu 自身漏洞、文本理解有歧义、异常操作导致的账号问题等开发组不承担任何责任，请在确保在阅读完用户手册、自行尝试运行效果后谨慎使用！**

## Star History

<a href="https://www.star-history.com/#SuperWaterGod/MaaGakumasu&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=SuperWaterGod/MaaGakumasu&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=SuperWaterGod/MaaGakumasu&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=SuperWaterGod/MaaGakumasu&type=Date" />
 </picture>
</a>

## 鸣谢

本项目由 **[MaaFramework](https://github.com/MaaXYZ/MaaFramework)** 强力驱动！
UI 由 [MFAAvalonia](https://github.com/SweetSmellFox/MFAAvalonia) 大力支持！

感谢以下开发者对本项目作出的贡献:

[![Contributors](https://contrib.rocks/image?repo=SuperWaterGod/MaaGakumasu&max=1000)](https://github.com/SuperWaterGod/MaaGakumasu/graphs/contributors)

## Join us

- MaaGakumasu 交流群 QQ 群：799823681
- MaaFramework 开发交流 QQ 群: 595990173
