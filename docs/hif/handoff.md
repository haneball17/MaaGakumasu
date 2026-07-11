# HIF 实测任务交接（2026-07-11）

本文用于暂时搁置 HIF 实机验证。以当前工作区为准；不要按旧会话记录回退任何文件。

## 当前结论

- 分支：`feat/hif`。
- 工作区存在大量未提交的 HIF 实现、资源和文档改动；**禁止**执行 `git reset --hard`、`git checkout --` 或覆盖现有修改。
- HIF 的离线安全层、Pipeline 静态检查和单元测试已可用；最近一次全量测试结果为 `116 passed`。
- MuMu 控制器已成功修复并实测可连接，但游戏仍停留在标题加载画面，尚未进入主页或 HIF 页面。
- 尚未对游戏内 HIF 执行任何培育、选项、卡牌或资源消耗操作。

## 已验证的实机环境

| 项目 | 值 |
| --- | --- |
| MuMu 安装目录 | `D:\game\MuMuPlayer-12.0` |
| 实例 | `1` / `MuMu安卓设备-1` |
| ADB 地址 | `127.0.0.1:16416` |
| ADB 可执行文件 | `D:\game\MuMuPlayer-12.0\nx_main\adb.exe` |
| 截图尺寸 | `720x1280` |
| HIF 帧契约 | 已通过 |

复测命令（只读，不发送点击）：

```powershell
python tools/hif_controller_probe.py --adb 127.0.0.1:16416 --adb-path "D:\game\MuMuPlayer-12.0\nx_main\adb.exe"
```

若 MuMu 实例未启动，可先只读确认状态：

```powershell
& "D:\game\MuMuPlayer-12.0\nx_main\MuMuManager.exe" info --vmindex 1
```

实例启动是正常实测前置条件；不要依据旧 HWND 连接。`MuMuManager.exe info --vmindex 1` 会给出当前 `adb_host_ip`、`adb_port`、`main_wnd` 和 `render_wnd`。

## 当前实机画面与阻塞

最近保存的证据位于 `debug/hif-live/`（调试文件，不提交）：

- `current-screen.png`：Android 游戏中心页。
- `after-game-load.png`、`after-second-title-tap.png`：游戏标题加载页。

已确认游戏包 `com.bandainamcoent.idolmaster_gakuen` 已安装并处于运行状态，但画面持续显示标题加载。继续盲点无法可靠到达主页，更不能作为 HIF Pipeline 的实机证据。

恢复时先让游戏自然进入主页；若需要用户登录、网络确认、维护提示或任何账户相关操作，应由用户处理后再继续。不要绕过这些状态，也不要在标题加载页反复发送触控。

## 当前实现与安全约束

### 核心模块

- `agent/hif/runtime.py`：标准帧验证与明确的裁剪坐标变换；外框截图只列候选裁剪，不自动猜测顶栏/底栏。
- `agent/hif/calibration.py`：版本化 ROI 校准读取；执行级校准必须带设备、游戏版本、语言和截图 SHA-256 证据。
- `agent/hif/image_io.py`：无需 Pillow/OpenCV 的 PNG 写入器，支持 Maa 返回的 `numpy.ndarray`。
- `agent/hif/journal.py`：HIF Journal、前后帧证据和离线审计。
- `agent/hif/pipeline_validation.py`：JSONC Pipeline 引用与 Custom Action 注册检查。
- `agent/custom/action/produce_hif.py`：HIF 页面操作统一走前后帧验证；Round 出牌默认观测，单步执行有完整状态与校准门。

### 必须保留的安全行为

1. `assets/data/hif/roi_calibration.json` 当前所有 `exam_numeric` 字段仍为 `null`，不能填入猜测坐标。
2. 默认只允许 `observe_and_stop`；`single_step` 需要完整且可追溯的校准；`continuous` 尚未开放。
3. 任意点击或滑动必须有唯一目标、前后截图和帧变化验证；失败后进入 `ProduceHIFUnknownStop`。
4. 不要把 MuMu 窗口外框偏移写入正式 Pipeline ROI 或点击坐标。
5. `debug/` 下截图和 Journal 只用于证据，不应提交。

## 恢复实测的步骤

### 1. 先验证设备和主页

```powershell
python tools/hif_controller_probe.py --adb 127.0.0.1:16416 --adb-path "D:\game\MuMuPlayer-12.0\nx_main\adb.exe" --save "debug\hif-live\home.png"
```

仅当输出中 `hif_frame_valid=true` 且截图已是游戏主页时继续。不要因为探测成功就假定 HIF 页面识别也正确。

### 2. 采集 HIF 页面样本

先在不消耗资源或经用户确认的前提下进入 HIF。本阶段优先收集：

1. HIF 本战准备页；
2. Round1 和 Round2 的出牌页；
3. Interval、饮料满仓、变卡、奖励、Live、结算和 Memory 页。

每个页面保存原始 `720x1280` PNG，并记录游戏版本、语言、DMM/汉化状态和控制器类型。

### 3. 校准 Round 数值 ROI

使用真实 HIF Round 截图校准以下字段：

- `good_condition`
- `reprise`
- `focus`
- `turn`
- `flow`
- `deck_size`
- `p_drinks`

命令示例：

```powershell
python tools/hif_roi_calibration.py --image <round.png> --field focus --roi x,y,width,height --device-id mumu12-device-1 --controller-kind adb --game-version <版本> --locale ja-JP --write
```

先省略 `--write` 进行 dry run。所有字段、设备标识和截图 SHA-256 齐全前，不要打开单步执行。

### 4. 分阶段运行

1. 先跑 `观测（默认）`，只检查 Journal、截图、候选和决策。
2. 对单个已校准 Round 开启 `单步执行（实验）`，每次只验证一张唯一目标卡。
3. 每次运行后审计：

```powershell
python tools/hif_journal_audit.py debug/hif-journal/<session>.jsonl
```

审计必须无失败项，才能扩大样本范围。连续模式需要完整实机闭环后另行评审，当前不开放。

## 本地验证命令

```powershell
python -m pytest -q
python tools/hif_pipeline_check.py
python -m py_compile agent/hif/*.py agent/hif/adapters/*.py agent/custom/action/produce_hif.py tools/hif_*.py
```

在当前环境中 `npx maa-tools check` 无法运行：npm registry 中没有可获取的 `maa-tools` 包。不要通过临时安装不明包伪造该检查结果。

## 交接前检查清单

- [x] MuMu ADB 连接及 `720x1280` 截图验证。
- [x] HIF 控制器探测支持显式 `--adb-path`。
- [x] 无 Pillow 环境下的 PNG 证据保存。
- [x] Journal 审计、Pipeline 静态检查和单元测试。
- [ ] 游戏主页稳定可达。
- [ ] HIF 页面实机截图样本。
- [ ] 全量 Round ROI 校准。
- [ ] Round1/2 单步实机验证。
- [ ] 完整 HIF 培育闭环和连续模式评审。
