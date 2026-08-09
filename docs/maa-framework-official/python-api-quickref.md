# MaaFramework Python API 速查

> 来源：maafw 5.11.1（`C:\Users\haneball\AppData\Roaming\Python\Python313\site-packages\maa\`）
> 用途：Custom recognition/action 开发时快速查阅方法签名，避免现读源码。
> 完整接口说明见同目录 `2.2-集成接口一览.md`，回调协议见 `2.3-回调协议.md`。

约定：

- 所有 `post_*` 方法均为**异步**，立即返回 `Job` / `TaskJob` / `JobWithResult`；通过 `.wait()` 阻塞等待、`.status` 查询状态、`.get()`（仅 `JobWithResult`）取结果值。
- `@property` 标注为属性，访问不加括号。
- 标 `Deprecated` 的方法保留但不应在新代码中使用。
- 枚举类（如 `LoggingLevelEnum`、`MaaAdbScreencapMethodEnum`）定义在 `maa/define.py`，本表只标注类名，值请查源码。
- `Job` / `TaskJob` / `JobWithResult` 定义在 `maa/job.py`；本表只标注返回类型，不展开其方法。

---

## Context（自定义识别/动作回调中最常用）

自定义动作 / 识别器收到的 `context` 就是这个类。可用于在回调里发截图、点击、跑子任务、覆盖 pipeline。

| 方法 / 属性 | 签名 | 返回 | 说明 |
| --- | --- | --- | --- |
| `run_task` | `run_task(entry: str, pipeline_override: Optional[dict[str, Any]] = None)` | `Optional[TaskDetail]` | 同步执行任务，失败返回 None |
| `run_recognition` | `run_recognition(entry: str, image: numpy.ndarray, pipeline_override: Optional[dict[str, Any]] = None)` | `Optional[RecognitionDetail]` | 同步执行识别（不跑后续 next）；用 `.hit` 判断是否命中 |
| `run_action` | `run_action(entry: str, box: RectType = (0, 0, 0, 0), reco_detail: str = "", pipeline_override: Optional[dict[str, Any]] = None)` | `Optional[ActionDetail]` | 同步执行动作（不跑后续 next）；用 `.success` 判断 |
| `run_recognition_direct` | `run_recognition_direct(reco_type: JRecognitionType, reco_param: JRecognitionParam, image: numpy.ndarray)` | `Optional[RecognitionDetail]` | 不经 pipeline entry，直接用识别类型 + 参数执行 |
| `run_action_direct` | `run_action_direct(action_type: JActionType, action_param: JActionParam, box: RectType = (0, 0, 0, 0), reco_detail: str = "")` | `Optional[ActionDetail]` | 不经 pipeline entry，直接用动作类型 + 参数执行 |
| `override_pipeline` | `override_pipeline(pipeline_override: dict[str, Any])` | `bool` | 覆盖当前 context 的 pipeline 配置 |
| `override_next` | `override_next(name: str, next_list: list[str])` | `bool` | 覆盖某节点 next 列表；节点不存在则失败 |
| `override_image` | `override_image(image_name: str, image: numpy.ndarray)` | `bool` | 覆盖指定名称的模板图片 |
| `get_node_data` | `get_node_data(name: str)` | `Optional[dict[str, Any]]` | 取节点当前定义（dict），不存在返回 None |
| `get_node_object` | `get_node_object(name: str)` | `Optional[JPipelineData]` | 同上，但解析为 `JPipelineData` 对象 |
| `tasker` | `@property` | `Tasker` | 取当前 Tasker 实例（最常用：`context.tasker.controller.post_click(...)`） |
| `get_task_job` | `get_task_job()` | `TaskJob` | 取当前任务 id 对应的 TaskJob；id 为 None 时抛 ValueError |
| `clone` | `clone()` | `Context` | 复制上下文；失败抛 ValueError |
| `set_anchor` | `set_anchor(anchor_name: str, node_name: str)` | `bool` | 设置锚点 → 节点映射 |
| `get_anchor` | `get_anchor(anchor_name: str)` | `Optional[str]` | 取锚点对应的节点名 |
| `get_hit_count` | `get_hit_count(node_name: str)` | `int` | 取节点命中计数（不存在返回 0） |
| `clear_hit_count` | `clear_hit_count(node_name: str)` | `bool` | 清除节点命中计数 |
| `wait_freezes` | `wait_freezes(time: int = 0, box: Optional[tuple[int, int, int, int]] = None, wait_freezes_param: Optional[JWaitFreezes] = None)` | `bool` | 等待画面静止；`time` 与 `wait_freezes_param.time` 互斥 |

> 回调中常见的截图方式：`img = context.tasker.controller.cached_image`（取最近截图），或 `context.tasker.controller.post_screencap().wait().get()`。

---

## CustomAction（自定义动作基类）

`maa/custom_action.py`。继承 `CustomAction(ABC)` 实现 `run`，再用 `Resource.register_custom_action` 或 `@resource.custom_action(name)` 注册。

抽象方法：

| 方法 | 签名 | 返回 | 说明 |
| --- | --- | --- | --- |
| `run` | `run(context: Context, argv: RunArg)` | `Union[RunResult, bool]` | 执行动作；返回 `RunResult(success=...)` 或 `bool`；返回 `None` 会被当作成功 |

`run` 收到的 `argv: CustomAction.RunArg`（dataclass）字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_detail` | `TaskDetail` | 当前任务详情 |
| `node_name` | `str` | 当前节点名 |
| `custom_action_name` | `str` | 自定义动作名（与 pipeline 中 `custom_action` 字段一致） |
| `custom_action_param` | `str` | 动作参数（**JSON 字符串**，需自行 `json.loads`） |
| `reco_detail` | `RecognitionDetail` | 前序识别详情 |
| `box` | `Rect` | 前序识别位置 `(x, y, w, h)` |

可选返回 `CustomAction.RunResult`（dataclass）字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `success` | `bool` | 动作是否成功 |

框架内部 property（一般无需调用）：

| 属性 | 返回 | 说明 |
| --- | --- | --- |
| `c_handle` | `Any` | C 回调函数指针，注册时由框架读取 |
| `c_arg` | `ctypes.c_void_p` | 透明传递给回调的 self 指针 |

典型写法：

```python
class MyAction(CustomAction):
    def run(self, context, argv):
        context.tasker.controller.post_click(100, 100).wait()
        return True
```

---

## CustomRecognition（自定义识别基类）

`maa/custom_recognition.py`。继承 `CustomRecognition(ABC)` 实现 `analyze`，再用 `Resource.register_custom_recognition` 或 `@resource.custom_recognition(name)` 注册。

抽象方法：

| 方法 | 签名 | 返回 | 说明 |
| --- | --- | --- | --- |
| `analyze` | `analyze(context: Context, argv: AnalyzeArg)` | `Union[AnalyzeResult, Optional[RectType]]` | 执行识别；返回 `(x, y, w, h)` 或 `AnalyzeResult`；返回 `None` 表示未识别到 |

`analyze` 收到的 `argv: CustomRecognition.AnalyzeArg`（dataclass）字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_detail` | `TaskDetail` | 当前任务详情 |
| `node_name` | `str` | 当前节点名 |
| `custom_recognition_name` | `str` | 识别器名 |
| `custom_recognition_param` | `str` | 识别器参数（**JSON 字符串**） |
| `image` | `numpy.ndarray` | 待识别图像（**BGR** 格式） |
| `roi` | `Rect` | 识别区域 `(x, y, w, h)` |

可选返回 `CustomRecognition.AnalyzeResult`（dataclass）字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `box` | `Optional[RectType]` | 识别到的位置；`None` 表示未识别到 |
| `detail` | `dict[str, Any]` | 识别详情，会写入识别结果 |

框架内部 property：同 `CustomAction`（`c_handle`、`c_arg`）。

典型写法：

```python
class MyReco(CustomRecognition):
    def analyze(self, context, argv):
        # 返回识别到的矩形，或 None
        return (100, 100, 50, 50)
```

---

## Tasker

`maa/tasker.py`。任务调度核心；自定义回调里通常通过 `context.tasker` 拿到。

| 方法 / 属性 | 签名 | 返回 | 说明 |
| --- | --- | --- | --- |
| `__init__` | `__init__(handle: Optional[MaaTaskerHandle] = None)` | — | 创建实例；传外部 handle 时不接管生命周期 |
| `bind` | `bind(resource: Resource, controller: Controller)` | `bool` | 关联 Resource 和 Controller |
| `resource` | `@property` | `Resource` | 取绑定的 Resource（失败抛 RuntimeError） |
| `controller` | `@property` | `Controller` | 取绑定的 Controller（失败抛 RuntimeError） |
| `inited` | `@property` | `bool` | 是否正确初始化 |
| `post_task` | `post_task(entry: str, pipeline_override: Optional[dict[str, Any]] = None)` | `TaskJob` | **异步**跑任务；返回的 TaskJob 可 `wait`/`get`/`override_pipeline` |
| `post_recognition` | `post_recognition(reco_type: JRecognitionType, reco_param: JRecognitionParam, image: numpy.ndarray)` | `TaskJob` | 异步执行识别（直接给类型+参数，不走 entry） |
| `post_action` | `post_action(action_type: JActionType, action_param: JActionParam, box: RectType = (0, 0, 0, 0), reco_detail: str = "")` | `TaskJob` | 异步执行动作（直接给类型+参数） |
| `running` | `@property` | `bool` | 是否仍在运行 |
| `post_stop` | `post_stop()` | `Job` | 异步停止；中断当前任务并停止资源/控制器操作 |
| `stopping` | `@property` | `bool` | 是否正在停止（尚未停止） |
| `get_latest_node` | `get_latest_node(name: str)` | `Optional[NodeDetail]` | 按任务名取最新节点详情 |
| `clear_cache` | `clear_cache()` | `bool` | 清理所有可查询信息 |
| `override_pipeline` | `override_pipeline(task_id: int, pipeline_override: dict[str, Any])` | `bool` | 运行中动态覆盖指定任务的 pipeline |
| `get_recognition_detail` | `get_recognition_detail(reco_id: int)` | `Optional[RecognitionDetail]` | 按 reco_id 取识别详情 |
| `get_action_detail` | `get_action_detail(action_id: int)` | `Optional[ActionDetail]` | 按 action_id 取动作详情 |
| `get_wait_freezes_detail` | `get_wait_freezes_detail(wf_id: int)` | `Optional[WaitFreezesDetail]` | 按 wf_id 取 wait-freezes 详情 |
| `get_node_detail` | `get_node_detail(node_id: int)` | `Optional[NodeDetail]` | 按 node_id 取节点详情 |
| `get_task_detail` | `get_task_detail(task_id: int)` | `Optional[TaskDetail]` | 按 task_id 取任务详情 |
| `add_sink` | `add_sink(sink: TaskerEventSink)` | `Optional[int]` | 添加 Tasker 级事件监听器，返回 sink_id |
| `remove_sink` | `remove_sink(sink_id: int)` | `None` | 移除 Tasker 级监听器 |
| `clear_sinks` | `clear_sinks()` | `None` | 清除全部 Tasker 级监听器 |
| `add_context_sink` | `add_context_sink(sink: ContextEventSink)` | `Optional[int]` | 添加 Context 级事件监听器 |
| `remove_context_sink` | `remove_context_sink(sink_id: int)` | `None` | 移除 Context 级监听器 |
| `clear_context_sinks` | `clear_context_sinks()` | `None` | 清除全部 Context 级监听器 |

静态方法（全局配置，`Tasker.set_xxx(...)` 调用）：

| 方法 | 签名 | 返回 | 说明 |
| --- | --- | --- | --- |
| `set_log_dir` | `set_log_dir(path: Union[Path, str])` | `bool` | 设置日志目录 |
| `set_save_draw` | `set_save_draw(save_draw: bool)` | `bool` | 识别可视化图存盘；开启后 `RecoDetail.draw_images` 才有值 |
| `set_stdout_level` | `set_stdout_level(level: LoggingLevelEnum)` | `bool` | stdout 日志级别 |
| `set_debug_mode` | `set_debug_mode(debug_mode: bool)` | `bool` | 调试模式：`RecoDetail` 可取 raw/draws，所有任务视为 focus |
| `set_save_on_error` | `set_save_on_error(save_on_error: bool)` | `bool` | 出错时把截图存到 `log/on_error` |
| `set_draw_quality` | `set_draw_quality(quality: int)` | `bool` | 可视化图 JPEG 质量（0–100，默认 85） |
| `set_reco_image_cache_limit` | `set_reco_image_cache_limit(limit: int)` | `bool` | 识别图缓存上限（默认 4096） |
| `load_plugin` | `load_plugin(path: Union[Path, str])` | `bool` | 加载插件（可给路径或名称，也支持递归目录） |
| `set_recording` | `set_recording(recording: bool)` | `bool` | **Deprecated**，恒返回 False |

---

## Controller

`maa/controller.py`。设备控制；自定义回调里通过 `context.tasker.controller` 取。

### Controller 基类公共方法

输入 / 触控（均异步，返回 `Job`）：

| 方法 | 签名 | 返回 | 说明 |
| --- | --- | --- | --- |
| `post_connection` | `post_connection()` | `Job` | 异步连接设备 |
| `post_click` | `post_click(x: int, y: int, contact: int = 0, pressure: int = 1)` | `Job` | 点击；`contact` 含义随控制器而异 |
| `post_swipe` | `post_swipe(x1: int, y1: int, x2: int, y2: int, duration: int, contact: int = 0, pressure: int = 1)` | `Job` | 滑动；`duration` 单位毫秒 |
| `post_click_key` | `post_click_key(key: int)` | `Job` | 单击虚拟键码 |
| `post_key_down` | `post_key_down(key: int)` | `Job` | 按下键 |
| `post_key_up` | `post_key_up(key: int)` | `Job` | 抬起键 |
| `post_input_text` | `post_input_text(text: str)` | `Job` | 输入文本 |
| `post_start_app` | `post_start_app(intent: str)` | `Job` | 启动应用（Adb：包名或 activity） |
| `post_stop_app` | `post_stop_app(intent: str)` | `Job` | 关闭应用 |
| `post_touch_down` | `post_touch_down(x: int, y: int, contact: int = 0, pressure: int = 1)` | `Job` | 按下 |
| `post_touch_move` | `post_touch_move(x: int, y: int, contact: int = 0, pressure: int = 1)` | `Job` | 移动 |
| `post_touch_up` | `post_touch_up(contact: int = 0)` | `Job` | 抬起 |
| `post_relative_move` | `post_relative_move(dx: int, dy: int)` | `Job` | 相对位移（仅 Win32） |
| `post_scroll` | `post_scroll(dx: int, dy: int)` | `Job` | 滚轮（建议用 120 的整数倍） |
| `post_inactive` | `post_inactive()` | `Job` | 设为不活跃（Win32 解除置顶+输入阻断；其余空操作） |
| `post_press_key` | `post_press_key(key: int)` | `Job` | **Deprecated**，转发到 `post_click_key` |

截图 / Shell：

| 方法 / 属性 | 签名 | 返回 | 说明 |
| --- | --- | --- | --- |
| `post_screencap` | `post_screencap()` | `JobWithResult[numpy.ndarray]` | 异步截图；`.wait().get()` 取 ndarray |
| `cached_image` | `@property` | `numpy.ndarray` | 最近一张截图（已按 target 尺寸缩放） |
| `post_shell` | `post_shell(cmd: str, timeout: int = 20000)` | `JobWithResult[str]` | 执行 shell（仅 ADB）；`-1` 表示无限等待 |
| `shell_output` | `@property` | `str` | 最近一次 shell 输出 |

状态 / 信息（均为 `@property`）：

| 属性 | 返回 | 说明 |
| --- | --- | --- |
| `connected` | `bool` | 是否已连接 |
| `uuid` | `str` | 设备 uuid（失败抛 RuntimeError） |
| `info` | `dict[str, Any]` | 控制器信息（类型、构造参数等） |
| `resolution` | `tuple[int, int]` | 设备**原始**分辨率（未缩放），首次截图后才有效，否则 `(0, 0)` |

选项 / Sink：

| 方法 / 属性 | 签名 | 返回 | 说明 |
| --- | --- | --- | --- |
| `set_mouse_lock_follow` | `set_mouse_lock_follow(enabled: bool)` | `bool` | 鼠标锁定跟随（Win32，用于 TPS/FPS） |
| `set_background_managed_keys` | `set_background_managed_keys(keys: Sequence[int])` | `bool` | 后台托管按键列表 |
| `set_screenshot_target_long_side` | `set_screenshot_target_long_side(long_side: int)` | `bool` | 截图缩放长边 |
| `set_screenshot_target_short_side` | `set_screenshot_target_short_side(short_side: int)` | `bool` | 截图缩放短边 |
| `set_screenshot_use_raw_size` | `set_screenshot_use_raw_size(enable: bool)` | `bool` | 截图不缩放（跨分辨率可能坐标错） |
| `set_screenshot_resize_method` | `set_screenshot_resize_method(method: int)` | `bool` | 缩放插值（cv::InterpolationFlags：NEAREST=0, LINEAR=1, CUBIC=2, AREA=3, LANCZOS4=4，默认 3） |
| `add_sink` | `add_sink(sink: ControllerEventSink)` | `Optional[int]` | 添加控制器事件监听器 |
| `remove_sink` | `remove_sink(sink_id: int)` | `None` | 移除监听器 |
| `clear_sinks` | `clear_sinks()` | `None` | 清除全部监听器 |

### Controller 子类（构造器，即工厂方法）

均继承 `Controller`，直接实例化即可。

| 类 | 构造签名 | 说明 |
| --- | --- | --- |
| `AdbController` | `AdbController(adb_path: Union[str, Path], address: str, screencap_methods: int = MaaAdbScreencapMethodEnum.Default, input_methods: int = MaaAdbInputMethodEnum.Default, config: Optional[dict[str, Any]] = None, agent_path: Union[str, Path] = AGENT_BINARY_PATH)` | Adb 控制器；截图/输入方式启动时测速选最快 |
| `Win32Controller` | `Win32Controller(hWnd: Union[ctypes.c_void_p, int, None], screencap_method: int = MaaWin32ScreencapMethodEnum.Background, mouse_method: int = MaaWin32InputMethodEnum.Seize, keyboard_method: int = MaaWin32InputMethodEnum.Seize)` | Win32 窗口控制器 |
| `MacOSController` | `MacOSController(window_id: int, screencap_method: int = MaaMacOSScreencapMethodEnum.ScreenCaptureKit, input_method: int = MaaMacOSInputMethodEnum.GlobalEvent)` | macOS 控制器 |
| `AndroidNativeController` | `AndroidNativeController(config: dict[str, Any])` | Android Native 控制器（部分构建不可用） |
| `PlayCoverController` | `PlayCoverController(address: str, uuid: str)` | macOS PlayCover iOS 应用 |
| `WlRootsController` | `WlRootsController(wlr_socket_path: str, use_win32_vk_code: bool = False)` | Linux wlroots |
| `DbgController` | `DbgController(read_path: Union[str, Path])` | 调试控制器，轮播目录图片 |
| `ReplayController` | `ReplayController(recording_path: Union[str, Path])` | 回放 RecordController 写入的 JSONL |
| `RecordController` | `RecordController(inner: Controller, recording_path: Union[str, Path])` | 包装内部控制器并录制 |
| `GamepadController` | `GamepadController(hWnd: Union[ctypes.c_void_p, int, None], gamepad_type: int = MaaGamepadTypeEnum.Xbox360, screencap_method: int = MaaWin32ScreencapMethodEnum.FramePool)` | 虚拟手柄（仅 Windows，需 ViGEm Bus） |

### CustomController（自定义控制器基类）

继承 `Controller`，实现下列方法后由框架回调。`@abstractmethod` 必须实现，其余可选。

| 方法 | 签名 | 返回 | 是否必须 |
| --- | --- | --- | --- |
| `connect` | `connect()` | `bool` | 必须 |
| `connected` | `connected()` | `bool` | 可选（默认 True） |
| `request_uuid` | `request_uuid()` | `str` | 必须 |
| `get_features` | `get_features()` | `int` | 可选（默认组合 feature 位） |
| `start_app` | `start_app(intent: str)` | `bool` | 必须 |
| `stop_app` | `stop_app(intent: str)` | `bool` | 必须 |
| `screencap` | `screencap()` | `numpy.ndarray` | 必须 |
| `click` | `click(x: int, y: int)` | `bool` | 必须 |
| `swipe` | `swipe(x1: int, y1: int, x2: int, y2: int, duration: int)` | `bool` | 必须 |
| `touch_down` | `touch_down(contact: int, x: int, y: int, pressure: int)` | `bool` | 必须 |
| `touch_move` | `touch_move(contact: int, x: int, y: int, pressure: int)` | `bool` | 必须 |
| `touch_up` | `touch_up(contact: int)` | `bool` | 必须 |
| `click_key` | `click_key(keycode: int)` | `bool` | 必须 |
| `input_text` | `input_text(text: str)` | `bool` | 必须 |
| `key_down` | `key_down(keycode: int)` | `bool` | 必须 |
| `key_up` | `key_up(keycode: int)` | `bool` | 必须 |
| `scroll` | `scroll(dx: int, dy: int)` | `bool` | 可选（默认 False） |
| `relative_move` | `relative_move(dx: int, dy: int)` | `bool` | 可选（默认 False） |
| `shell` | `shell(cmd: str, timeout: int)` | `Optional[str]` | 可选（默认 None） |
| `inactive` | `inactive()` | `bool` | 可选（默认 True） |
| `get_custom_info` | `get_custom_info()` | `dict[str, Any]` | 可选（默认空 dict） |

---

## Resource

`maa/resource.py`。资源管理 + 自定义识别/动作注册入口。

### 加载 / 覆盖 / 查询

| 方法 / 属性 | 签名 | 返回 | 说明 |
| --- | --- | --- | --- |
| `__init__` | `__init__(handle: Optional[MaaResourceHandle] = None)` | — | 创建实例；传外部 handle 时不接管生命周期 |
| `post_bundle` | `post_bundle(path: Union[Path, str])` | `Job` | 异步加载资源 bundle |
| `post_ocr_model` | `post_ocr_model(path: Union[Path, str])` | `Job` | 异步加载 OCR 模型目录 |
| `post_pipeline` | `post_pipeline(path: Union[Path, str])` | `Job` | 异步加载 pipeline（目录或单个 json/jsonc） |
| `post_image` | `post_image(path: Union[Path, str])` | `Job` | 异步加载图片资源（目录或单图） |
| `override_pipeline` | `override_pipeline(pipeline_override: dict[str, Any])` | `bool` | 覆盖 pipeline 配置 |
| `override_next` | `override_next(name: str, next_list: list[str])` | `bool` | 覆盖节点 next 列表（节点不存在也会创建） |
| `override_image` | `override_image(image_name: str, image: numpy.ndarray)` | `bool` | 覆盖指定名称图片 |
| `get_node_data` | `get_node_data(name: str)` | `Optional[dict[str, Any]]` | 取节点定义（dict） |
| `get_node_object` | `get_node_object(name: str)` | `Optional[JPipelineData]` | 取节点定义（对象） |
| `get_default_recognition_param` | `get_default_recognition_param(reco_type: JRecognitionType)` | `Optional[JRecognitionParam]` | 取某识别类型的默认参数 |
| `get_default_action_param` | `get_default_action_param(action_type: JActionType)` | `Optional[JActionParam]` | 取某动作类型的默认参数 |
| `clear` | `clear()` | `bool` | 清除已加载内容（加载中会失败） |

### 状态 / 信息（`@property`）

| 属性 | 返回 | 说明 |
| --- | --- | --- |
| `loaded` | `bool` | 资源是否加载正常 |
| `node_list` | `list[str]` | 所有任务节点名 |
| `custom_recognition_list` | `list[str]` | 已注册自定义识别器名 |
| `custom_action_list` | `list[str]` | 已注册自定义动作名 |
| `hash` | `str` | 资源 hash |

### 推理后端

| 方法 | 签名 | 返回 | 说明 |
| --- | --- | --- | --- |
| `use_cpu` | `use_cpu()` | `bool` | 用 CPU 推理 |
| `use_directml` | `use_directml(device_id: int = MaaInferenceDeviceEnum.Auto)` | `bool` | 用 DirectML（Windows） |
| `use_coreml` | `use_coreml(coreml_flag: int = MaaInferenceDeviceEnum.Auto)` | `bool` | 用 CoreML（macOS） |
| `use_auto_ep` | `use_auto_ep()` | `bool` | 自动选执行提供者 |
| `set_gpu` | `set_gpu(gpu_id: int)` | `bool` | **Deprecated**，转发到 `use_directml` |
| `set_cpu` | `set_cpu()` | `bool` | **Deprecated**，转发到 `use_cpu` |
| `set_auto_device` | `set_auto_device()` | `bool` | **Deprecated**，转发到 `use_auto_ep` |

### 注册自定义识别 / 动作

| 方法 | 签名 | 返回 | 说明 |
| --- | --- | --- | --- |
| `custom_recognition` | `custom_recognition(name: str)` | `Callable[[type[CustomRecognition]], type[CustomRecognition]]` | **装饰器**：注册自定义识别器类 |
| `register_custom_recognition` | `register_custom_recognition(name: str, recognition: CustomRecognition)` | `bool` | 注册识别器**实例** |
| `unregister_custom_recognition` | `unregister_custom_recognition(name: str)` | `bool` | 移除指定识别器 |
| `clear_custom_recognition` | `clear_custom_recognition()` | `bool` | 清除全部识别器 |
| `custom_action` | `custom_action(name: str)` | `Callable[[type[CustomAction]], type[CustomAction]]` | **装饰器**：注册自定义动作类 |
| `register_custom_action` | `register_custom_action(name: str, action: CustomAction)` | `bool` | 注册动作**实例** |
| `unregister_custom_action` | `unregister_custom_action(name: str)` | `bool` | 移除指定动作 |
| `clear_custom_action` | `clear_custom_action()` | `bool` | 清除全部动作 |

### Sink

| 方法 | 签名 | 返回 | 说明 |
| --- | --- | --- | --- |
| `add_sink` | `add_sink(sink: ResourceEventSink)` | `Optional[int]` | 添加资源事件监听器 |
| `remove_sink` | `remove_sink(sink_id: int)` | `None` | 移除监听器 |
| `clear_sinks` | `clear_sinks()` | `None` | 清除全部监听器 |

---

## 顶层导出（`maa/__init__.py`）

`__init__.py` 本身只做 `Library.open(path, agent_server=False)` 初始化，不显式 `__all__` 导出。各子模块需显式 `from maa.tasker import Tasker` 等导入。枚举与句柄类型（`MaaTaskId`、`LoggingLevelEnum`、`MaaAdbScreencapMethodEnum` 等）来自 `maa/define.py`，由各模块 `from .define import *` 引入。
