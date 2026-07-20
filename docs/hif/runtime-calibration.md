# HIF 实机校准与运行手册

HIF 的常规页面自动执行仅接受 MuMu 原始竖屏 `720x1280` 截图。唯一方向例外是 `Round2` 结束后播放的 Live 视频：它为横屏 `1280x720`，须命中独立 Live 锚点并保持观察，不得复用竖屏 ROI 或发送输入。窗口外框、远程桌面缩放或其他横屏截图都会触发安全停止，不能通过手改点击坐标绕过。截图方向的权威说明见 [`resources.md`](resources.md)。

## 1. 先验证控制器

以下命令只枚举 MaaFramework 可见的 ADB 和桌面窗口，不会点击游戏：

```powershell
python tools/hif_controller_probe.py
```

若找到可用控制器，再执行只读截图探测：

```powershell
python tools/hif_controller_probe.py --adb 127.0.0.1:16384
python tools/hif_controller_probe.py --hwnd <窗口句柄>
```

若系统 PATH 未配置 `adb`，请显式传入 MuMu 自带的可执行文件，避免 MaaFramework 在连接后截图失败：

```powershell
python tools/hif_controller_probe.py --adb 127.0.0.1:<adb_port> --adb-path "<MuMu 安装目录>\nx_main\adb.exe"
```

可通过 `MuMuManager.exe info --vmindex <index>` 查询实例的 `adb_host_ip` 与 `adb_port`。探测工具也支持 `--save <png>` 保存明确指定的只读截图，供后续 ROI 校准。

输出必须包含 `"hif_frame_valid": true` 才能开始 HIF 测试。

## 2. 校准出牌 ROI

先用 MuMu 截图工具保存 HIF Round 页面原始 PNG，再校验尺寸：

```powershell
python tools/hif_roi_calibration.py --image <截图.png>
```

确认一个字段的 ROI 后，先 Dry run：

```powershell
python tools/hif_roi_calibration.py --image <截图.png> --field focus --roi 100,200,80,40
```

核对输出后才追加 `--write`。校准保存于 `assets/data/hif/roi_calibration.json`；未校准字段保持 `null`，单步和连续模式都会拒绝点击。

执行级校准还必须关联到稳定设备与原始截图证据。例如：

```powershell
python tools/hif_roi_calibration.py --image <原始截图.png> --field focus --roi 100,200,80,40 --device-id mumu12-device-1 --controller-kind adb --game-version <游戏版本> --locale ja-JP --write
```

工具会写入截图 SHA-256、校准时间和设备元数据。只有同一份校准中所有出牌必需字段、设备标识和截图哈希齐全，`单步执行` 才可能进入点击审批。

控制器探测若发现窗口外框截图比 `720x1280` 更高，只会列出候选裁剪，绝不会自动猜测顶栏或底栏。必须先用原始截图确认裁剪方向，并在专用运行器中同时应用到截图、ROI 与点击坐标；不要改写正式 Pipeline 的坐标。

## 3. 执行级别

- `观测（默认）`：只写入 `debug/hif-journal/`，到关键节点安全停止。
- `单步执行（实验）`：只适用于莉波好调预设；每次只点击一张经过唯一识别的卡，并检查点击后帧已变化。
- 连续模式尚未开放。它需要完成出牌 ROI、跨回合状态和完整实机回归后才能启用。

## 4. 收集故障证据

出现安全停止时请保留：

- `debug/hif-journal/*.jsonl` 和其中引用的截图；
- 模拟器类型、控制器方式、游戏版本、是否汉化/DMM；
- 当前页面的原始 `720x1280` 截图。

不要提交 `debug/` 下的运行日志和截图。

运行后可离线审计 Journal，确认每一条标记为 `verified` 的动作都具有不同的前后帧指纹：

```powershell
python tools/hif_journal_audit.py debug/hif-journal/<session>.jsonl
```

审计失败代表证据不足，不能作为开放连续执行的依据。
