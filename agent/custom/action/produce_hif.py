import re
import json
import time
import dataclasses
from typing import Any, Dict, List, Optional
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
from PIL import Image
from utils import logger
from maa.context import Context
from maa.custom_action import CustomAction
from maa.agent.agent_server import AgentServer

from agent.hif.presets import (
    HIFPreset,
    parse_hif_preset,
    apply_file_overrides,
    build_scoring_params,
    choose_first_matching,
    choose_schedule_priority,
    build_gui_keyword_overrides,
    validate_select_change_source_names,
)
from agent.hif.decisions import viewer
from agent.hif.decisions.play import GarakutaRinamiStrategy
from agent.hif.decisions.state import (
    ROUND1_PLAY_RECORD_FIELDS,
    ExamRound,
    ExamState,
    ActionKind,
    CardAction,
)
from agent.hif.decisions.config import ProfilePayload
from agent.hif.decisions.rewards import load_keyword_tables
from agent.hif.decisions.scoring import (
    DecisionContext,
    match_drink_name,
    match_pitem_name,
    score_card_by_name,
    score_drink_by_name,
)
from agent.hif.adapters.card_dict import normalize_card_name, build_card_name_dict
from agent.hif.decisions.schedule import classify_class_option
from agent.hif.adapters.exam_reader import ExamStateReader


class _ProduceHIFActionBase(CustomAction):
    CLICK_DELAY = 0.4
    ACTION_DELAY = 2.0
    # 决策存档目录:绝对定位(agent 由 MFA/插件启动时 cwd 未必是仓库根)
    # parents[3]: produce_hif.py 在 agent/custom/action/ 下,需上溯 3 级到仓库根(parents[2] 是 agent/,实证 2026-08-15 存档全部写入 agent/debug/)
    _DECISIONS_DIR = Path(__file__).resolve().parents[3] / "debug" / "decisions"
    # 会话状态(跨 hif_run 分段持久):day_remaining=当前日程;select_change_active=変卡流程在途标记
    # (区分真変卡完成页与日程收尾的支援卡随机强化演出页——后者不记决策日志,用户定案 2026-08-15)
    _SESSION_STATE_FILE = _DECISIONS_DIR / "session-state.json"
    SELECT_CHANGE_FLAG = "select_change_active"
    # Round1 局内会话命名空间（出牌跨回合字段：turn/cards_played/oneesan_used/natural_finisher_used/reprise_count）
    ROUND1_STATE_KEY = "round1"
    # round1 子树字段清单（D1）：画面外跨回合状态，出牌循环读写，新局开始 reset 清零
    ROUND1_STATE_FIELDS = ("turn", "cards_played", "oneesan_used", "natural_finisher_used", "reprise_count")
    # Round1 出牌落盘的 screen_state 名（F3；对应 debug/decisions/<ts>_round1_play.png 命名）
    ROUND1_PLAY_SCREEN = "round1_play"

    @staticmethod
    def _read_session_state() -> dict:
        try:
            data = json.loads(_ProduceHIFActionBase._SESSION_STATE_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @classmethod
    def _write_session_state(cls, patch: dict) -> None:
        state = cls._read_session_state()
        state.update(patch)
        state["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            cls._SESSION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            cls._SESSION_STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _read_session_day() -> Optional[int]:
        return _ProduceHIFActionBase._read_session_state().get("day_remaining")

    @classmethod
    def _set_session_day(cls, day_remaining: Optional[int]) -> None:
        if day_remaining is not None:
            cls._write_session_state({"day_remaining": day_remaining})

    @classmethod
    def _read_round1_state(cls) -> dict:
        """读 session-state 的 round1 子树（缺失/非 dict 返回空 dict，不抛异常）。"""
        round1 = cls._read_session_state().get(cls.ROUND1_STATE_KEY)
        return round1 if isinstance(round1, dict) else {}

    @classmethod
    def _write_round1_state(cls, patch: dict) -> None:
        """对 round1 子树做 patch 合并写入（不动顶层 day_remaining 等字段）。"""
        round1 = cls._read_round1_state()
        round1.update(patch)
        cls._write_session_state({cls.ROUND1_STATE_KEY: round1})

    @classmethod
    def _reset_round1_state(cls) -> None:
        """新局 Round1 开始时整体重置局内字段（防上局残留污染；Phase 2 出牌节点入口调用）。

        整体替换而非 patch 合并——round1 子树里不应有本局之外的键。
        """
        prev = cls._read_round1_state()
        cls._write_session_state({
            cls.ROUND1_STATE_KEY: {
                "turn": 0,
                "cards_played": 0,
                "oneesan_used": False,
                "natural_finisher_used": False,
                "reprise_count": 0,
                # 同局跨段保留:段重入不再点瓶位探测(実機 2026-08-22 轮2 用户观察
                #「尝试喝饮料」=每段重入点开 Pドリンク詳細弹窗读名的观感;
                # 槽位内容局内稳定,陈旧度可接受——拦截模式只读不消费)
                "p_drink_slots": prev.get("p_drink_slots") or [],
            }
        })

    # ------------------------------------------------------------------
    # 操作日志链（2026-08-22 轮2 grill 裁决）：决策日志之外,记录每次点击/滑动/按键
    # + 操作后结果截图(debug/decisions/ops/)。IPC 点击丢失类 bug(#14/21)复盘用。
    # _tap/_swipe/_key 为唯一入口,post_click/post_swipe 直调一律替换。
    # ------------------------------------------------------------------

    _OPS_DIR = _DECISIONS_DIR / "ops"
    _OP_SEQ = 0

    @classmethod
    def _fingerprint(cls, image) -> str:
        """画面指纹：64x64 灰度缩略图 sha1（变化判定用,非精确感知哈希）。"""
        try:
            arr = np.asarray(image)
            if arr.ndim != 3:
                return ""
            pil = Image.fromarray(arr[..., ::-1]).convert("L").resize((64, 64))
            import hashlib
            return hashlib.sha1(np.asarray(pil).tobytes()).hexdigest()[:16]
        except Exception:
            return ""

    OP_TIMEOUT_S = 15  # 单次 controller 操作(点击/滑动/按键)完成上限

    @classmethod
    def _wait_job(cls, job, timeout_s: float = None) -> bool:
        """带超时的 Job 等待:maafw Job.wait() 无限阻塞(controller/IPC 卡死时 agent
        线程永久挂起,実機 2026-08-22 hang 场景之一)。done 轮询替代,超时告警返回
        False(操作可能未执行,调用方按点击丢失重试路径处理)。"""
        deadline = time.time() + (timeout_s if timeout_s is not None else cls.OP_TIMEOUT_S)
        while not getattr(job, "done", True):  # 无 done 属性(mock/异常 Job)视为已完成
            if time.time() > deadline:
                logger.warning(f"HIF 操作超时 {cls.OP_TIMEOUT_S}s(controller 无响应,视为未执行)")
                return False
            time.sleep(0.2)
        return True

    @classmethod
    def _safe_fingerprint(cls, context: Context) -> str:
        """操作前指纹（截图失败返回空串=放弃变化判定,操作照常执行）。"""
        try:
            return cls._fingerprint(cls._get_screenshot(context))
        except Exception:
            return ""

    @classmethod
    def _op_log(cls, context: Context, op: str, detail: dict, before_fp: str = "") -> None:
        """操作后记录：截图落盘 + ops JSONL(scene_changed 由前后指纹对比)。"""
        try:
            time.sleep(0.8)
            image = cls._get_screenshot(context)
            cls._OPS_DIR.mkdir(parents=True, exist_ok=True)
            cls._OP_SEQ += 1
            ts = time.strftime("%Y%m%d-%H%M%S")
            png = cls._OPS_DIR / f"{ts}_{cls._OP_SEQ:04d}.png"
            after_fp = cls._fingerprint(image)
            try:
                Image.fromarray(np.ascontiguousarray(image[..., ::-1])).save(png)
            except Exception:
                png = None
            record = {"ts": time.strftime("%H:%M:%S"), "op": op, "seq": cls._OP_SEQ, **detail}
            if png:
                record["after_png"] = str(png)
            if before_fp:
                record["scene_changed"] = bool(after_fp) and after_fp != before_fp
            else:
                # 三态化(P0-2):before 指纹采集失败时显式写 null(未判定),
                # 勿静默缺字段——下游无法区分「未采集」与「没变化」
                record["scene_changed"] = None
            with (cls._DECISIONS_DIR / f"ops-{time.strftime('%Y%m%d')}.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as err:
            logger.debug(f"HIF 操作日志失败(不阻断): {err}")

    @classmethod
    def _tap(cls, context: Context, x: int, y: int) -> None:
        """守卫点击：全 agent 侧点击唯一入口（记录坐标+结果截图+画面变化）。"""
        before = cls._safe_fingerprint(context)
        cls._wait_job(context.tasker.controller.post_click(x, y))
        cls._op_log(context, "click", {"x": x, "y": y}, before_fp=before)

    @classmethod
    def _swipe(cls, context: Context, x1: int, y1: int, x2: int, y2: int, duration: int) -> None:
        """守卫滑动：全 agent 侧滑动唯一入口。"""
        before = cls._safe_fingerprint(context)
        cls._wait_job(context.tasker.controller.post_swipe(x1, y1, x2, y2, duration=duration))
        cls._op_log(context, "swipe", {"from": [x1, y1], "to": [x2, y2], "duration": duration}, before_fp=before)

    @classmethod
    def _key(cls, context: Context, keycode: int) -> None:
        """守卫按键（BACK 等）。"""
        before = cls._safe_fingerprint(context)
        cls._wait_job(context.tasker.controller.post_click_key(keycode))
        cls._op_log(context, "key", {"keycode": keycode}, before_fp=before)

    @staticmethod
    def _get_screenshot(context: Context):
        return context.tasker.controller.post_screencap().wait().get()

    @classmethod
    def _click_box_center(cls, context: Context, box: List[int], double: bool = True, y_offset: int = 0) -> bool:
        if not box or len(box) < 4:
            return False

        x = box[0] + box[2] // 2
        y = box[1] + box[3] // 2 + y_offset
        cls._tap(context, x, y)
        if double:
            time.sleep(_ProduceHIFActionBase.CLICK_DELAY)
            cls._tap(context, x, y)
        return True

    @staticmethod
    def _run_ocr(context: Context, image, name: str, expected: list[str] | str, roi: list[int]):
        return context.run_recognition(
            name,
            image,
            pipeline_override={name: {"recognition": "OCR", "expected": expected, "roi": roi}},
        )

    @staticmethod
    def _run_template(context: Context, image, name: str, template: list[str] | str, roi: list[int], threshold: float = 0.8):
        return context.run_recognition(
            name,
            image,
            pipeline_override={name: {"recognition": "TemplateMatch", "template": template, "roi": roi, "threshold": threshold}},
        )

    @classmethod
    def _stop_unknown(cls, context: Context, reason: str) -> bool:
        logger.warning(f"HIF 安全停止: {reason}")
        # 全量日志:安全停止也存档(截图+原因),复盘直接看当时页面
        cls._archive_static(context, "unknown_stop", {"action": "stop", "reason": reason, "evidence_empty": True})
        # 返回 False 让节点动作失败终止任务;run_task(UnknownStop) 只能停子任务流,父管线会继续轮询
        return False

    @staticmethod
    def _get_preset(argv: CustomAction.RunArg) -> HIFPreset:
        # 覆盖链:GUI(custom_action_param) > decision_override.json(非评分项) > preset 默认
        return apply_file_overrides(parse_hif_preset(argv.custom_action_param))

    def _stop_unsupported(self, context: Context, screen_state: str, reason: str) -> bool:
        logger.warning(f"HIF 安全停止: screen_state={screen_state}, reason={reason}")
        self._archive_static(context, screen_state, {
            "action": "stop", "reason": reason, "evidence_empty": True,
        })
        return False

    def _find_text_option(self, context: Context, image, phrases: tuple[str, ...], roi: list[int]):
        for phrase in phrases:
            # 短语是字面量(含 preset 卡名如「アピールの基本+」),+ 等元字符不转义会被
            # MaaFW regex_valid 拒掉整个 override(実機 2026-08-20)
            reco_detail = self._run_ocr(
                context, image, "ProduceRecognitionHIFTextOption", [f".*{re.escape(phrase)}.*"], roi
            )
            if reco_detail and reco_detail.hit:
                return reco_detail
        return None

    @staticmethod
    def _get_health(context: Context, image) -> Optional[dict]:
        # HIF 本战为竖屏 720x1280,体力在顶部中央 [285,16,150,85];不复用初培育横屏 ROI
        reco_detail = context.run_recognition(
            "ProduceRecognitionHealth",
            image,
            pipeline_override={"ProduceRecognitionHealth": {"roi": [285, 16, 150, 85]}},
        )
        if not (reco_detail and reco_detail.hit):
            return None

        try:
            health_parts = reco_detail.best_result.text.split("/")
            current_health = int(health_parts[0])
            max_health = int(health_parts[1])
            ratio = current_health / max_health
            logger.info(f"体力: {current_health}/{max_health} ({ratio:.2%})")
            return {"current": current_health, "max": max_health, "ratio": ratio}
        except (ValueError, IndexError, ZeroDivisionError):
            logger.warning("体力数据解析失败")
            return None

    def _get_day_remaining(self, context: Context, image) -> Optional[int]:
        reco_detail = self._run_ocr(
            context,
            image,
            "ProduceRecognitionHIFRemainingDay",
            [".*[1-6]日.*"],
            [30, 25, 160, 145],
        )
        if not (reco_detail and reco_detail.hit):
            return None

        digits = "".join(char for char in reco_detail.best_result.text if char.isdigit())
        day_remaining = int(digits) if digits else None
        logger.info(f"HIF 剩余日数: {day_remaining}")
        return day_remaining

    @staticmethod
    def _archive_decision(image, screen_state: str, record: dict) -> None:
        """决策落盘(全决策点共用):截图 debug/decisions/<ts>_<state>.png + session JSONL + 自动刷新查看器 HTML。

        staticmethod:_archive_static(classmethod)经 cls 调用时无实例,非静态会参数错位且异常被吞。
        """
        try:
            out_dir = _ProduceHIFActionBase._DECISIONS_DIR
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d-%H%M%S")
            # 截图失败只丢图不丢记录(IPC 代理进程的 screencap 可能返回非 ndarray,実機 2026-08-15 双进程环境实证)
            img_path = out_dir / f"{ts}_{screen_state}.png"
            try:
                # maafw post_screencap 返回 BGR 通道序,PIL 按 RGB 解释会红蓝互换,翻通道后再保存
                Image.fromarray(np.ascontiguousarray(image[..., ::-1])).save(img_path)
                record["image"] = str(img_path)
            except Exception as err:
                logger.warning(f"HIF 决策截图失败(记录仍写入): {err}")
                img_path.unlink(missing_ok=True)
                record["evidence_empty"] = True
            record.setdefault("ts", time.strftime("%H:%M:%S"))
            record.setdefault("screen", screen_state)
            # 注入会话 day(记录自带时不覆盖;状态文件由日程选择时更新)
            if "day_remaining" not in record:
                session_day = _ProduceHIFActionBase._read_session_day()
                if session_day is not None:
                    record["day_remaining"] = session_day
            jsonl = out_dir / f"session-{time.strftime('%Y%m%d')}.jsonl"
            with jsonl.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            # 决策时自动刷新 HTML 查看器(grill 定案);失败不阻断决策
            try:
                viewer.refresh(out_dir)
            except Exception as err:
                logger.warning(f"HIF 决策查看器刷新失败: {err}")
        except Exception as err:  # 存档失败不阻断决策
            logger.warning(f"HIF 决策存档失败: {err}")

    @classmethod
    def _archive_static(cls, context: Context, screen_state: str, record: dict) -> None:
        """类方法入口的安全停止存档(截图自取,失败静默——停止路径不能被存档异常掩盖)。"""
        try:
            cls._archive_decision(cls._get_screenshot(context), screen_state, record)
        except Exception:
            pass

    @staticmethod
    def build_round1_play_record(
        state: ExamState,
        action: CardAction,
        played_cards: Optional[List[str]] = None,
        turn_score: Optional[int] = None,
        dry_run: bool = False,
        evidence: Optional[dict] = None,
        exec_verified: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """组装 Round1 出牌落盘记录（F3，纯函数可离线单测）。

        前六字段对齐 roundsim ManualTurnRecord（turn/flow/played_cards/good_condition_turns/
        stamina/turn_score，実機手记口径，供 tools/hif_replay_report.py 回放对比）；
        后六字段为実機执行层扩展（action/target_card/reason/dry_run/exec_verified/
        evidence，evidence 含点击 box 坐标与 OCR 原文；exec_verified=出牌执行确认，
        dry_run 拦截类记录保持 None=未执行不判定）。缺省字段显式带 None/[]/{}，
        保证逐回合 JSONL schema 稳定（缺回合数据可辨「未记录」而非「字段缺失」）。
        """
        record: Dict[str, Any] = dict.fromkeys(ROUND1_PLAY_RECORD_FIELDS)
        record.update({
            "turn": state.turn,
            "flow": state.current_flow,
            "played_cards": list(played_cards or []),
            "good_condition_turns": state.good_condition_turns,
            "stamina": state.stamina,
            "turn_score": turn_score,
            "action": action.kind.value,
            "target_card": action.target_card,
            "reason": action.reason,
            "dry_run": dry_run,
            "exec_verified": exec_verified,
            "evidence": evidence or {},
        })
        return record

    @classmethod
    def _archive_round1_play(cls, image, record: dict, screen_state: str = "") -> None:
        """Round1/Round2 出牌决策落盘（F3，ProduceHIFRound1Play 每回合调用）。

        先按 ROUND1_PLAY_RECORD_FIELDS 做防御性重排（调用方乱序/缺键也输出
        schema 稳定的记录，extra 键保留在后），再走共用存档链
        （截图 + session JSONL + viewer 刷新，与 _archive_decision 同模式）。
        screen_state 空时用默认 round1_play（R2 参数化传 round2_play）。
        """
        ordered = {key: record.get(key) for key in ROUND1_PLAY_RECORD_FIELDS}
        for key, value in record.items():
            if key not in ordered:
                ordered[key] = value
        cls._archive_decision(image, screen_state or cls.ROUND1_PLAY_SCREEN, ordered)


@AgentServer.custom_action("ProduceChooseHIFEventAuto")
class ProduceChooseHIFEventAuto(_ProduceHIFActionBase):
    LOW_HEALTH_RATIO = 0.35
    LOW_HEALTH_VALUE = 10

    EVENT_CONFIG = {
        "相談": "produce/chat.png",
        "おでかけ": "produce/go_out.png",
        "课程": "produce/lesson.png",
        # HIF 専用差し入れ模板(実機 2026-08-21 Day3 取证卡 [371,939,139,121];
        # 旧 produce/event.png 对当前 UI 仅 0.4775,且与初流程共用不可覆盖)
        "活动": "produce/event_hif.png",
    }
    EVENT_PRESET_KEYS = {
        "相談": "consult",
        "おでかけ": "go_out",
        "课程": "lesson",
        "活动": "gift",
        "Vo": "Vo",
        "Da": "Da",
        "Vi": "Vi",
    }

    # HIF 日程候选卡属性扫描(实机 hif_day1.png 720x1280 校准,场景卡 SC-201/501)
    # 卡片结构:左上紫蓝渐变 [146,143,255]±30,右下属性扇形(粉=Vo/蓝=Da/橙=Vi)
    GRADIENT_BAND = slice(940, 970)
    GRADIENT_COLOR = (146, 143, 255)
    GRADIENT_MIN_CLUSTER_WIDTH = 30
    CARD_TOP_LEFT_Y = 919
    CARD_CLICK_CENTER = (70, 1000 - 919)
    FAN_REGION = (74, 992, 50, 38)
    ATTRIBUTE_COLORS = {
        "Vo": (208, 144, 207),
        "Da": (99, 185, 245),
        "Vi": (213, 203, 161),
    }
    ATTRIBUTE_COLOR_MAX_DISTANCE = 60

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        logger.success("事件: HIF 选择日程")
        image = self._get_screenshot(context)
        health_data = self._get_health(context, image) or {"current": 34, "max": 34, "ratio": 1.0}
        events = self._get_available_events(context, image)

        if not events:
            logger.warning("未识别到 HIF 可选日程，保持当前状态")
            return True

        preset = self._get_preset(argv)
        day_remaining = self._get_day_remaining(context, image)
        if day_remaining is not None:
            _ProduceHIFActionBase._set_session_day(day_remaining)
        # 新日程开始=上一轮変卡流程必然已结束,兜底清在途标记(防中断残留)
        _ProduceHIFActionBase._write_session_state({_ProduceHIFActionBase.SELECT_CHANGE_FLAG: False})
        best_event = self._choose_best_event(health_data, events, preset, day_remaining)
        if not best_event:
            return self._stop_unsupported(context, "finals_action_select", "preset_no_matching_event")

        logger.info(f"HIF 选择事件: {best_event['name']}")
        self._archive_decision(image, "finals_action_select", {
            "action": "pick_event",
            "day_remaining": day_remaining,
            "health": f"{health_data['current']}/{health_data['max']}",
            "candidates": [e["name"] for e in events],
            "all_options": self._survey_all_options(context, image),
            "chosen": best_event["name"],
            "priority": choose_schedule_priority(preset, day_remaining),
        })
        return self._execute_event(context, best_event)

    def _choose_best_event(
        self,
        health_data: dict,
        events: list[dict],
        preset: HIFPreset,
        day_remaining: int | None,
    ) -> Optional[dict]:
        current_health = health_data["current"]
        ratio_health = health_data["ratio"]

        low_ratio = (preset.low_health_percent / 100) if preset.low_health_percent else self.LOW_HEALTH_RATIO
        if current_health <= self.LOW_HEALTH_VALUE or ratio_health <= low_ratio:
            logger.info(f"HIF 低体力({current_health}, {ratio_health:.0%} ≤ {low_ratio:.0%}): 强制おでかけ")
            go_out = self._find_event(events, "おでかけ")
            if go_out:
                return go_out

        priority = choose_schedule_priority(preset, day_remaining)
        if priority is None:
            return None
        available = {self.EVENT_PRESET_KEYS[event["name"]]: event for event in events}
        selected_key = choose_first_matching(available, priority)
        return available.get(selected_key) if selected_key else None

    def _find_event(self, events: list[dict], target_name: str) -> Optional[dict]:
        for event in events:
            if event["name"] == target_name:
                return event
        return None

    def _execute_event(self, context: Context, event: dict) -> bool:
        if not self._click_box_center(context, event["box"]):
            return self._stop_unknown(context, f"???? HIF ??: {event.get('name', 'unknown')}")

        time.sleep(self.ACTION_DELAY)
        return True

    # HIF 公開レッスン候选卡(实机 hif_day2.png 校准):三卡底部彩色横条
    # 有固定文字「Vo./Da./Vi.公開レッスン」,OCR 前缀映射属性;SP 徽章与体力标记三卡相同不作区分
    PUBLIC_LESSON_ROI = [80, 1040, 570, 100]
    PUBLIC_LESSON_CLICK_Y = 1010
    PUBLIC_LESSON_PREFIXES = {"Vo.": "Vo", "Da.": "Da", "Vi.": "Vi"}

    def _get_available_events(self, context: Context, image) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        log_names: List[str] = []

        for event in self._scan_attribute_cards(image):
            events.append(event)
            log_names.append(event["name"])

        for event in self._scan_public_lessons(context, image):
            events.append(event)
            log_names.append(event["name"])

        roi = [0, 840, 720, 280]
        for event_name, template in self.EVENT_CONFIG.items():
            reco_detail = self._run_template(context, image, "ProduceRecognitionHIFEvent", template, roi, threshold=0.78)
            if reco_detail and reco_detail.hit:
                events.append({"name": event_name, "box": reco_detail.best_result.box})
                log_names.append(event_name)

        if log_names:
            logger.info(f"HIF 可用日程: {', '.join(log_names)}")
        return events

    # 全量选项探测(仅存档不参与决策):低阈值模板捕获 0.78 决策线以下的真实选项
    # (実機 2026-08-21 Day3 差し入れ 0.4775 盲区教训——candidates 只记识别命中的,
    # 页面实有未识别项事后要 vision 复核截图才能还原,决策模块切换行动项缺数据)
    SURVEY_TEMPLATE_THRESHOLD = 0.4
    EVENT_ROI = [0, 840, 720, 280]

    def _survey_all_options(self, context: Context, image) -> List[Dict[str, Any]]:
        options: List[Dict[str, Any]] = []
        for event in self._scan_attribute_cards(image):
            options.append({"name": event["name"], "box": event["box"], "source": "color_scan"})
        for lesson in self._scan_public_lessons(context, image):
            options.append({"name": lesson["name"], "box": lesson["box"], "source": "ocr"})
        for event_name, template in self.EVENT_CONFIG.items():
            reco_detail = self._run_template(
                context, image, "ProduceRecognitionHIFEventSurvey", template, self.EVENT_ROI, threshold=self.SURVEY_TEMPLATE_THRESHOLD
            )
            if reco_detail and reco_detail.all_results:
                best = max(reco_detail.all_results, key=lambda r: r.score)
                options.append({"name": event_name, "box": best.box, "score": round(best.score, 3), "source": "template_survey"})
        return options

    def _scan_public_lessons(self, context: Context, image) -> List[Dict[str, Any]]:
        """识别公開レッスン候选卡:OCR 底部横条固定文字,前缀映射 Vo/Da/Vi。"""
        reco_detail = self._run_ocr(
            context, image, "ProduceRecognitionHIFPublicLesson", [".*公開レッスン.*"], self.PUBLIC_LESSON_ROI
        )
        lessons: List[Dict[str, Any]] = []
        if not (reco_detail and reco_detail.all_results):
            return lessons
        for item in reco_detail.all_results:
            text = item.text.replace(" ", "")
            for prefix, name in self.PUBLIC_LESSON_PREFIXES.items():
                if prefix in text:
                    center_x = item.box[0] + item.box[2] // 2
                    lessons.append({"name": name, "box": [center_x, self.PUBLIC_LESSON_CLICK_Y, 1, 1]})
                    logger.info(f"HIF 公開レッスン候选: {name} @({center_x},{self.PUBLIC_LESSON_CLICK_Y}) text={text!r}")
                    break
        return lessons

    def _scan_attribute_cards(self, image) -> List[Dict[str, Any]]:
        """两步法识别 Vo/Da/Vi 授業候选:渐变带定位卡片列,扇形平均色分类属性。

        模板匹配对 50x38 纯色小扇形区分度不足(实测同源仅 0.55-0.65),
        颜色分类距离 <30,已对 hif_day1.png 三卡全中(9/11/14)。
        """
        arr = np.asarray(image)
        if arr.ndim != 3 or arr.shape[0] < self.FAN_REGION[1] + self.FAN_REGION[3]:
            logger.warning(f"HIF 色扫描: 图像形状异常 {None if not hasattr(arr, 'shape') else arr.shape}")
            return []
        # maafw post_screencap 返回 OpenCV BGR 序,属性色参考值为 RGB,需翻转
        if arr.shape[2] >= 3:
            arr = arr[..., :3][..., ::-1]

        band = arr[self.GRADIENT_BAND].astype(int)
        r, g, b = band[:, :, 0], band[:, :, 1], band[:, :, 2]
        gr, gg, gb = self.GRADIENT_COLOR
        gradient_mask = (np.abs(r - gr) < 30) & (np.abs(g - gg) < 30) & (b > 225)
        xs_sorted = np.sort(np.nonzero(gradient_mask)[1]) if gradient_mask.any() else np.array([], dtype=int)
        clusters: List[tuple[int, int]] = []
        start = prev = None
        for x in xs_sorted:
            if prev is None:
                start = prev = int(x)
                continue
            if x - prev > 20:
                clusters.append((start, prev))
                start = int(x)
            prev = int(x)
        if start is not None:
            clusters.append((start, prev))

        cards: List[Dict[str, Any]] = []
        for cluster_start, cluster_end in clusters:
            if cluster_end - cluster_start < self.GRADIENT_MIN_CLUSTER_WIDTH:
                continue
            fan_dx, fan_y, fan_w, fan_h = self.FAN_REGION
            fan = arr[fan_y : fan_y + fan_h, cluster_start + fan_dx : cluster_start + fan_dx + fan_w].astype(int)
            if fan.size == 0:
                continue
            avg = fan.reshape(-1, 3).mean(axis=0)
            best_name, best_distance = None, 1e9
            for name, ref in self.ATTRIBUTE_COLORS.items():
                distance = float(np.sqrt(((avg - np.array(ref)) ** 2).sum()))
                if distance < best_distance:
                    best_name, best_distance = name, distance
            if best_name is None or best_distance > self.ATTRIBUTE_COLOR_MAX_DISTANCE:
                logger.warning(f"HIF 候选卡属性色未识别: cluster_x={cluster_start}, RGB={avg.astype(int)}, d={best_distance:.0f}")
                continue
            card_x = cluster_start - 10
            center_x = card_x + self.CARD_CLICK_CENTER[0]
            center_y = self.CARD_TOP_LEFT_Y + self.CARD_CLICK_CENTER[1]
            cards.append({"name": best_name, "box": [center_x, center_y, 1, 1], "attribute_rgb": avg.astype(int).tolist()})
            logger.info(f"HIF 候选卡: {best_name} @({center_x},{center_y}) RGB={avg.astype(int).tolist()} d={best_distance:.0f}")
        return cards


@AgentServer.custom_action("ProduceChooseHIFPItemAuto")
class ProduceChooseHIFPItemAuto(_ProduceHIFActionBase):
    OPTION_ROI = [40, 300, 640, 760]
    OPTION_CANDIDATES = [
        [360, 610, 1, 1],
        [360, 790, 1, 1],
        [360, 970, 1, 1],
    ]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        logger.success("事件: HIF 选择 P 道具")
        image = self._get_screenshot(context)

        recommend = self._find_recommend(context, image)
        if recommend:
            logger.info("命中推荐 P 道具")
            self._archive_decision(image, "hif_p_item_select", {"action": "pick", "mode": "recommend"})
            if not self._click_box_center(context, recommend, double=False, y_offset=80):
                return self._stop_unsupported(context, "hif_p_item_select", "recommend_click_failed")
            time.sleep(self.ACTION_DELAY)
            return True

        keyword_hit = self._find_keyword_option(context, image)
        if keyword_hit:
            logger.info(f"按关键词选择 HIF P 道具: {keyword_hit['name']}")
            self._archive_decision(image, "hif_p_item_select", {
                "action": "pick", "mode": "keyword", "chosen": keyword_hit["name"],
            })
            if not self._click_box_center(context, keyword_hit["box"], double=False):
                return self._stop_unsupported(context, "hif_p_item_select", "keyword_click_failed")
            time.sleep(self.ACTION_DELAY)
            return True

        return self._stop_unsupported(context, "hif_p_item_select", "preset_p_item_not_found")

    def _find_recommend(self, context: Context, image) -> Optional[List[int]]:
        reco_detail = self._run_template(
            context,
            image,
            "ProduceRecognitionHIFRecommend",
            ["produce/recommend.png", "produce/event_recommend.png"],
            self.OPTION_ROI,
            threshold=0.78,
        )
        if reco_detail and reco_detail.hit:
            return reco_detail.best_result.box
        return None

    def _find_keyword_option(self, context: Context, image) -> Optional[Dict[str, Any]]:
        keyword_order = [
            ("Pポイント", [".*Pポイント.*"]),
            ("相談", [".*相談.*"]),
            ("Pドリンク", [".*Pドリンク.*", ".*ドリンク.*"]),
        ]
        for name, expected in keyword_order:
            reco_detail = self._run_ocr(context, image, f"ProduceRecognitionHIFPItem{name}", expected, self.OPTION_ROI)
            if reco_detail and reco_detail.hit:
                return {"name": name, "box": reco_detail.best_result.box}
        return None


@AgentServer.custom_action("ProduceChooseHIFClassOptionAuto")
class ProduceChooseHIFClassOptionAuto(_ProduceHIFActionBase):
    """授業事件选项:好调文案优先,未命中时选最上方的非トラブル追加选项。

    选项文案随事件而变(实测 メンタルケア 事件文案与日志记录完全不同),
    无法穷举;页面锚用左上「授業」标题(Flag 侧),选项选择用两级策略。
    """

    OPTION_ROI = [40, 620, 640, 360]
    GOOD_CONDITION_OPTIONS = ("余裕です！", "長い道のりでした")
    TROUBLE_MARKER = "トラブル"
    TRANSITION_DELAY = 1.2
    # 对话中间页空白推进点(同 ProduceHIFSelectChangeDoneAuto,実機 2026-08-15 逐位试探有效)
    BLANK_TAP = (360, 1000)
    # 选项文案至少含 2 个日文字符,排除「-50」等数字消耗标记与「T」等图标噪读
    OPTION_TEXT_PATTERN = re.compile(r"[ぁ-んァ-ヶ一-龯a-zA-Z]{2,}")

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        priority = self._get_preset(argv).class_option_priority
        if "good_condition" not in priority and "first_safe" not in priority:
            return self._stop_unsupported(context, "hif_class_options", "preset_no_class_option_policy")

        image = self._get_screenshot(context)
        if "good_condition" in priority:
            reco_detail = self._find_text_option(context, image, self.GOOD_CONDITION_OPTIONS, self.OPTION_ROI)
            if reco_detail:
                if not self._click_box_center(context, reco_detail.best_result.box, double=False):
                    return self._stop_unsupported(context, "hif_class_options", "good_condition_option_click_failed")
                logger.info(f"HIF 授業选项: 好调文案命中「{reco_detail.best_result.text}」")
                self._archive_decision(image, "hif_class_options", {
                    "action": "pick_option", "strategy": "good_condition",
                    "chosen": reco_detail.best_result.text,
                })
                return True
        if "first_safe" not in priority:
            return self._stop_unsupported(context, "hif_class_options", "good_condition_option_not_found")
        return self._choose_first_safe_option(context, image)

    # 转场竞态防循环(実機 2026-08-15 Day4):変卡标题未渲染时 Flag 误命中残留「授業」标题,
    # 同一无效文本被反复点击;记录最近点击文本,重复时跳过换下一个候选
    _recent_option_texts: list[str] = []
    # 誤入変卡页放行计数(#48):[JumpBack] 回环命中即重置轮询永不到 timeout,
    # 连续放行上限后必须回退到安全停止
    _change_handoff_count = 0

    def _handoff_to_change_flow(self, context: Context) -> bool:
        """誤入変卡弹窗自检放行（#48）：変卡页与授業页共享左上「授業」HUD 且选项
        区文本全被安全过滤排空——OCR 弹窗标题区「チェンジ」命中即 return True 交回
        路由让 SelectChangeTarget/SourceFlag 接管（其长句锚稳定后可命中）；连续 3 次
        仍被路由回本 action 说明変卡 Flag 持续 miss，False 回退安全停止防死循环。"""
        image = self._get_screenshot(context)
        hit = self._find_text_option(context, image, ("チェンジ",), [60, 250, 600, 130])
        cls = type(self)
        if not hit:
            cls._change_handoff_count = 0
            return False
        cls._change_handoff_count += 1
        if cls._change_handoff_count > 3:
            logger.warning("HIF 授業选项: 変卡页放行 3 次仍被路由回,変卡 Flag 疑持续 miss,停止")
            cls._change_handoff_count = 0
            return False
        logger.info(f"HIF 授業选项: 检出変卡弹窗(誤入),放行回路由({cls._change_handoff_count}/3)")
        return True

    def _choose_first_safe_option(self, context: Context, image) -> bool:
        reco_detail = self._run_ocr(context, image, "ProduceRecognitionHIFClassOptions", [".*"], self.OPTION_ROI)
        if not (reco_detail and reco_detail.all_results):
            # 誤入自愈（実機轮7 #48：変卡页与授業页共享左上「授業」HUD——変卡 Flag
            # 长句锚 miss 时 ClassOptionFlag 在変卡页误命中，选项过滤后全空 stop，
            # 损耗一次段重启）——先自检是否変卡弹窗，是则放行回路由
            if self._handoff_to_change_flow(context):
                return True
            return self._stop_unsupported(context, "hif_class_options", "class_options_not_found")

        results = reco_detail.all_results
        trouble_ys = [item.box[1] + item.box[3] // 2 for item in results if self.TROUBLE_MARKER in item.text]
        candidates = [
            item
            for item in results
            if item.box[3] > 20
            and self.OPTION_TEXT_PATTERN.search(item.text.replace("ß", ""))
            and self.TROUBLE_MARKER not in item.text
            # 排除页面指令文案(実機 2026-08-15:「受け取るスキルカードを選んでください。」被误当选)
            and "ください" not in item.text
            and not any(abs(item.box[1] + item.box[3] // 2 - ty) < 40 for ty in trouble_ys)
        ]
        if not candidates:
            if self._handoff_to_change_flow(context):
                return True
            return self._stop_unsupported(context, "hif_class_options", "no_safe_option")

        # 固定表标记可见时(選択して獲得)优先获得类选项(seesaawiki 授業固定表),否则取最上方安全项
        acquire_candidates = [item for item in candidates if classify_class_option(item.text) == "acquire"]
        ordered = acquire_candidates + [c for c in candidates if c not in acquire_candidates]
        recent = type(self)._recent_option_texts
        target = next((c for c in ordered if c.text not in recent), ordered[0])
        # 全部候选都点过一轮仍停在原地 → 清空守卫重新开始(避免卡死)
        if target.text in recent:
            recent.clear()

        if not self._click_box_center(context, target.box, double=False):
            return self._stop_unsupported(context, "hif_class_options", "safe_option_click_failed")
        # 流转验证(実機 2026-08-15:选项点击后进预览页,残留授業标题致 Flag 再命中连点 7 次):
        # 点击后同文本仍在原位 = 当时不是选项页(実機 2026-08-20:授業事件对话中间页
        # 台词被误当选项,点台词无跳变),点空白推进对话后 return True 让 [JumpBack]
        # 回 ScheduleRoot 重路由;连续多次仍无变化才安全停止防死循环
        time.sleep(self.TRANSITION_DELAY)
        verify = self._run_ocr(context, self._get_screenshot(context), "ProduceRecognitionHIFClassOptions", [".*"], self.OPTION_ROI)
        still_there = any(
            item.text == target.text and abs(item.box[1] - target.box[1]) < 20
            for item in (verify.all_results if verify else [])
        )
        if still_there:
            cls = type(self)
            cls._blank_tap_count = getattr(cls, "_blank_tap_count", 0) + 1
            if cls._blank_tap_count > 4:
                return self._stop_unsupported(
                    context, "hif_class_options", f"blank_tap_no_transition: {target.text}"
                )
            logger.info(
                f"HIF 授業选项: 「{target.text}」点击无跳变,判定为对话中间页,点空白推进"
                f"(第{cls._blank_tap_count}次)"
            )
            self._tap(context, *self.BLANK_TAP)
            time.sleep(self.ACTION_DELAY)
            return True
        type(self)._blank_tap_count = 0
        recent.append(target.text)
        del recent[:-3]
        logger.info(f"HIF 授業选项: 通用安全策略选择「{target.text}」")
        self._archive_decision(image, "hif_class_options", {
            "action": "pick_option", "strategy": "first_safe",
            "candidates": [item.text for item in results],
            "chosen": target.text,
        })
        return True


class _ProduceHIFRewardChoiceAction(_ProduceHIFActionBase):
    """三选一奖励基类:逐张点选候选,读详情面板卡名+效果文本做关键词评分,选最高分确认。

    候选缩略图上无文字(実機 2026-08-15 确认),卡名与效果只在点选后的白色详情面板渲染;
    点选是选中而非确认(确认另有 受け取る/次へ 按钮),逐张读取安全。
    决策透明度(2026-08-15 grill):评分明细日志、截图存档、JSONL 落盘、确认后流转验证;
    名单优先:卡名命中 preset.card/drink_priority 直接选(用户指定 > 评分器)。
    """

    SELECT_DELAY = 1.2
    REROLL_ROI = [530, 1000, 180, 140]
    # 三个固定候选位(三列布局,列间距约 152px;[待実機校准] 第二/三列为对称推算)
    CANDIDATE_BOXES: list[list[int]] = []
    DETAIL_TEXT_ROI: list[int] = []
    # 详情面板卡名行(daily-log 実測 y512-560;此前 DETAIL_TEXT_ROI 从 y555 起漏读卡名 43px)
    CARD_NAME_ROI: list[int] = [120, 500, 480, 70]
    CONFIRM_TEXT: tuple[str, ...] = ()
    CONFIRM_ROI: list[int] = []
    # 本页标题锚(流转验证:确认后仍见此文本=未流转)
    ANCHOR_TEXT: tuple[str, ...] = ()
    ANCHOR_ROI: list[int] = []

    _CARD_DICT: list[str] | None = None

    def _read_all_text(self, context: Context, image, name: str, roi: list[int]) -> str:
        reco_detail = self._run_ocr(context, image, name, [".*"], roi)
        if not (reco_detail and reco_detail.all_results):
            return ""
        return " ".join(item.text for item in reco_detail.all_results)

    def _read_card_name(self, context: Context, image) -> str:
        """读详情面板卡名行;词典约束候选(卡名 121+子类扩展),normalize 修正误识。"""
        if _ProduceHIFRewardChoiceAction._CARD_DICT is None:
            _ProduceHIFRewardChoiceAction._CARD_DICT = build_card_name_dict()
        dict_names = _ProduceHIFRewardChoiceAction._CARD_DICT + self._extra_name_dict()
        # 词典 expected 走 maafw IPC 偶发 UTF-8→GBK 乱码(実機 2026-08-20 三选一/手牌
        # 均出现过,单词条不受影响),且 + 等元字符需转义;改为全量 OCR + Python 侧
        # 子串匹配词典,绕开大列表传输
        reco_detail = self._run_ocr(context, image, "ProduceRecognitionHIFCardName", [".*"], self.CARD_NAME_ROI)
        if not (reco_detail and reco_detail.all_results):
            return ""
        norm_names = {normalize_card_name(name): name for name in dict_names}
        for item in reco_detail.all_results:
            text = item.text.strip()
            hit = norm_names.get(normalize_card_name(text))
            if hit:
                return hit
            for name in dict_names:
                if name in text:
                    return name
        return ""

    def _extra_name_dict(self) -> list[str]:
        """子类扩展名词典(如饮料页追加 drinks.json 名单),默认空。"""
        return []

    def _choose_keyword_reward(self, context: Context, preset: HIFPreset, reroll_limit: int, screen_state: str) -> bool:
        table = load_keyword_tables(overrides=build_gui_keyword_overrides(preset))[preset.preference]
        priority_names = preset.drink_priority if "drink" in screen_state else preset.card_priority
        # 评分模型接线(B3):卡/饮料名命中效果池走结构化数值评分,miss 退关键词兜底(断崖为零);
        # 局面信号(B2):三选一页顶部 HUD 体力 + 日数(session 状态,日程页写入)
        scoring_params = build_scoring_params(preset)
        is_drink_page = "drink" in screen_state
        hud_image = self._get_screenshot(context)
        try:
            health = self._get_health(context, hud_image)
        except Exception:  # HUD 遮挡/识别链路异常退中性信号,不阻断三选一决策
            health = None
        decision_ctx = DecisionContext(
            stamina_ratio=health["ratio"] if health else None,
            days_remaining=self._read_session_day(),
        )
        logger.info(
            "HIF 三选一局面信号: "
            f"体力比率={decision_ctx.stamina_ratio if health else '未知'} 日数={decision_ctx.days_remaining if decision_ctx.days_remaining is not None else '未知'}"
        )
        best_box = None
        for round_index in range(reroll_limit + 1):
            candidates = []
            for label, box in enumerate(self.CANDIDATE_BOXES, start=1):
                self._click_box_center(context, box, double=False)
                time.sleep(self.SELECT_DELAY)
                image = self._get_screenshot(context)
                card_name = self._read_card_name(context, image)
                # 关键词评分恒算(对照基线,离线回放差异表双评分消费);决策分命中效果池时用模型分
                text = self._read_all_text(context, image, "ProduceRecognitionHIFRewardDetail", self.DETAIL_TEXT_ROI)
                keyword_score, keyword_breakdown = table.score_detail(text)
                model = None
                if card_name:
                    model = (score_drink_by_name if is_drink_page else score_card_by_name)(
                        card_name, decision_ctx, scoring_params
                    )
                if model is not None:
                    score = model.total
                    breakdown = [(item.note, item.points) for item in model.breakdown]
                    score_source = "effects"
                else:
                    score, breakdown = keyword_score, keyword_breakdown
                    score_source = "keywords"
                candidates.append({
                    "label": label, "box": box, "card": card_name, "text": text, "score": score,
                    "breakdown": breakdown, "keyword_score": keyword_score, "score_source": score_source,
                })
                detail_str = ",".join(f"{kw}{value:+g}" for kw, value in breakdown) or "无命中"
                logger.info(
                    f"HIF 三选一[{screen_state}] 候选{label}: {card_name or '卡名未读'} "
                    f"score={score:.1f}[{score_source}] [{detail_str}]"
                )

            # 名单优先:用户点名的卡/饮料直接选(grill 定案:用户指定 > 评分器)
            chosen = next((c for c in candidates if c["card"] and c["card"] in priority_names), None)
            if chosen:
                logger.info(f"HIF 三选一[{screen_state}] 名单优先: 「{chosen['card']}」(跳过评分)")
            else:
                chosen = max(candidates, key=lambda c: c["score"])
                if table.accepts(chosen["score"]):
                    pass  # 达标直接确认
                else:
                    reroll = self._find_text_option(context, self._get_screenshot(context), ("再抽選",), self.REROLL_ROI)
                    if reroll and round_index < reroll_limit:
                        logger.info(
                            f"HIF 三选一[{screen_state}] 最高分 {chosen['score']:.0f} 未达阈值 {table.accept_threshold:.0f},重抽"
                        )
                        self._archive_decision(self._get_screenshot(context), screen_state, {
                            "round": round_index,
                            "preference": preset.preference, "candidates": candidates, "action": "reroll",
                            "accept_threshold": table.accept_threshold,
                            "overrides": build_gui_keyword_overrides(preset) or None,
                        })
                        self._click_box_center(context, reroll.best_result.box, double=False)
                        time.sleep(self.ACTION_DELAY)
                        continue
            self._archive_decision(self._get_screenshot(context), screen_state, {
                "round": round_index,
                "preference": preset.preference, "candidates": candidates, "action": "confirm",
                "chosen": chosen["label"], "chosen_card": chosen["card"] or None,
                "accept_threshold": table.accept_threshold,
                "overrides": build_gui_keyword_overrides(preset) or None,
            })
            return self._confirm_candidate(context, chosen["box"], screen_state)

        return self._confirm_candidate(context, best_box, screen_state)

    def _confirm_candidate(self, context: Context, box: List[int], screen_state: str) -> bool:
        # y+20 pill 几何中心补偿(実機 2026-08-22 轮5 #35 模式:受け取る/次へ OCR 文字
        # box 中心偏上 ~21px,入场点击静默丢失高发)
        self._click_box_center(context, box, double=False, y_offset=20)
        time.sleep(self.CLICK_DELAY)
        confirm = self._find_text_option(context, self._get_screenshot(context), self.CONFIRM_TEXT, self.CONFIRM_ROI)
        if not confirm:
            return self._stop_unsupported(context, screen_state, "confirm_button_not_found")
        if not self._click_box_center(context, confirm.best_result.box, double=False):
            return self._stop_unsupported(context, screen_state, "confirm_button_click_failed")
        time.sleep(self.ACTION_DELAY)
        # 流转验证(grill 定案):确认后本页标题锚仍在=确认未生效,安全停止防同页重复决策
        if self.ANCHOR_TEXT:
            still = self._find_text_option(context, self._get_screenshot(context), self.ANCHOR_TEXT, self.ANCHOR_ROI)
            if still:
                return self._stop_unsupported(context, screen_state, "confirm_no_transition")
        return True


@AgentServer.custom_action("ProduceChooseHIFDrinkRewardAuto")
class ProduceChooseHIFDrinkRewardAuto(_ProduceHIFRewardChoiceAction):
    """P 饮料三选一:逐张点选读卡名+效果,名单(饮料名)优先,评分选最高分确认(无重抽)。"""

    CANDIDATE_BOXES = [[158, 822, 127, 127], [308, 822, 127, 127], [458, 822, 127, 127]]
    DETAIL_TEXT_ROI = [118, 506, 500, 230]
    CONFIRM_TEXT = ("受け取る", "次へ")
    CONFIRM_ROI = [150, 1000, 420, 200]
    ANCHOR_TEXT = ("受け取るPドリンク", "Pドリンクを選んで")
    ANCHOR_ROI = [80, 540, 560, 220]

    _drink_names: list[str] | None = None

    def _extra_name_dict(self) -> list[str]:
        """饮料页名词典追加 drinks.json 28 种(実機 2026-08-15:纯卡词典读饮料名全空)。"""
        if ProduceChooseHIFDrinkRewardAuto._drink_names is None:
            names: list[str] = []
            try:
                payload = json.loads((Path(__file__).resolve().parents[2] / "assets" / "data" / "hif" / "drinks.json").read_text(encoding="utf-8"))
                names = [d["name_jp"] for d in payload.get("drinks", []) if d.get("name_jp")]
            except Exception:
                names = []
            ProduceChooseHIFDrinkRewardAuto._drink_names = names
        return ProduceChooseHIFDrinkRewardAuto._drink_names

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        return self._choose_keyword_reward(context, self._get_preset(argv), reroll_limit=0, screen_state="hif_drink_reward")


@AgentServer.custom_action("ProduceChooseHIFSkillRewardAuto")
class ProduceChooseHIFSkillRewardAuto(_ProduceHIFRewardChoiceAction):
    """技能卡三选一:逐张点选读卡名+效果,名单(卡名)优先,评分;不达阈值且见「再抽選」才重抽。"""

    CANDIDATE_BOXES = [[156, 821, 128, 128], [308, 821, 128, 128], [460, 821, 128, 128]]
    DETAIL_TEXT_ROI = [118, 555, 490, 185]
    CONFIRM_TEXT = ("受け取る", "次へ")
    CONFIRM_ROI = [150, 1000, 420, 200]
    ANCHOR_TEXT = ("受け取るスキルカード", "スキルカードを選んで")
    ANCHOR_ROI = [80, 540, 560, 220]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        reroll = preset.reward_reroll_override or preset.reward_reroll_limit
        return self._choose_keyword_reward(context, preset, reroll_limit=reroll, screen_state="hif_skill_reward")


@AgentServer.custom_action("ProduceChooseHIFSelectChangeTargetAuto")
class ProduceChooseHIFSelectChangeTargetAuto(_ProduceHIFRewardChoiceAction):
    """変卡第一阶段:逐张点选候选读卡名+效果评分选最高分,确认后推进到牌库选择。"""

    CANDIDATE_BOXES = [[156, 837, 128, 128], [308, 837, 128, 128], [460, 837, 128, 128]]
    DETAIL_TEXT_ROI = [118, 555, 490, 185]
    CONFIRM_TEXT = ("次へ",)
    CONFIRM_ROI = [200, 1010, 320, 130]
    ANCHOR_TEXT = ("チェンジで獲得する",)
    ANCHOR_ROI = [60, 260, 600, 110]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        # 変卡流程在途标记:完成页据此区分真変卡与日程收尾的支援卡随机强化演出页
        _ProduceHIFActionBase._write_session_state({_ProduceHIFActionBase.SELECT_CHANGE_FLAG: True})
        preset = self._get_preset(argv)
        # reroll 强制 0(2026-08-22 轮1 実機 3 次 IPC hang 均在変卡 reroll 循环内——
        # 重抽点击+加载窗口的高密度 run_recognition 触发 maafw 5.11 死锁;直选最高分
        # 不重抽,决策质量损失可接受,后续 maafw 修复后恢复 preset 重抽上限)
        return self._choose_keyword_reward(context, preset, reroll_limit=0, screen_state="select_change_target")


@AgentServer.custom_action("ProduceChooseHIFSelectChangeSourceAuto")
class ProduceChooseHIFSelectChangeSourceAuto(_ProduceHIFActionBase):
    """変卡第二阶段：逐格点选读卡名 → 全库收集 → 名单优先选源卡 → チェンジ确认。

    実機校准 2026-08-21（debug/autodev/round1/stage2_screen*_sample.json，本 action
    首次実行即命中名单[0]大胆不敵并完成チェンジ）：
    - 网格 3 行×4 列（YOLO 实测，与 98496e9 投影差 45px 以实测为准）：列中心
      x=139/285/431/578，行中心 y=695/845/995
    - 选中态卡名带 [60,255,560,315]（y315 以下压到效果首行会混入噪声，勿放宽），
      crop 放大 2 倍 OCR；卡面本身无任何卡名文字（旧 _find_text_option 扫名单
      设计性 miss 的根因）
    - チェンジ按钮（选中态）[465,1141,115,36]；トラブル卡选中时按钮不亮 →
      以按钮 OCR 不到为不可変信号，fallback 顺延下一格（本局牌库无トラブル，
      形态未直采，按钮不亮重试路径为保守实现）
    - 滚动 300px（2 行）保持网格对齐；360px 会偏 44px 导致行粘连（実測）

    grill 共识（2026-08-21，9 项裁决）：全库收集+deck snapshot 落盘（roundsim
    校准输入）；名单 miss → 非トラブル第一格 fallback 告警不停机；验收四条
    （mode=named 落盘/链路推进/全库≤45s/纯逻辑单测），実機验收挂 Phase 4+日常兜底。
    """

    GRID_COLS = (139, 285, 431, 578)
    GRID_ROWS = (695, 845, 995)
    NAME_ZONE = (60, 255, 560, 315)
    CHANGE_BUTTON_ROI = [380, 1100, 280, 110]
    SCROLL_FROM = (360, 1040)
    SCROLL_TO = (360, 740)  # 300px 滚动（実機滚动量随网格回弹浮动,重叠行由整屏判底吸收）
    MAX_SCREENS = 6  # 22 基本卡+応援棒补卡 ≈26 张/12 格=3 屏+判底屏+余量（2026-08-22 轮2）
    CELL_CLICK_DELAY = 1.6
    FALLBACK_MAX_TRIES = 4  # トラブル格按钮不亮时的顺延重试上限

    CUSTOMIZE_CONFIRM_ROI = [20, 430, 680, 220]  # カスタマイズ確認/強化確認弹窗标题带(実機 y484/y433)
    CUSTOMIZE_CONFIRM_TAP = (520, 1157)          # 弹窗チェンジ按钮（実機 2026-08-22 手动成功位）

    def _dismiss_customize_confirm(self, context: Context) -> bool:
        """段重启时残留的源卡確認弹窗接管（実機 2026-08-22 轮1:上段选中源卡后弹窗
        出现即 stop,下段扫描被弹窗遮挡 scroll_back 恒败死循环）。命中即点チェンジ
        完成変卡——比取消好（选中态已就绪）。"""
        image = self._get_screenshot(context)
        hit = self._find_text_option(context, image, ("カスタマイズ確認",), self.CUSTOMIZE_CONFIRM_ROI)
        if not hit:
            return False
        logger.info("HIF 変卡: 接管残留カスタマイズ確認弹窗,点チェンジ完成")
        self._tap(context, *self.CUSTOMIZE_CONFIRM_TAP)
        time.sleep(self.ACTION_DELAY)
        self._archive_decision(self._get_screenshot(context), "select_change_source_deck", {
            "action": "resume_confirm_changi", "note": "残留弹窗接管",
        })
        return True

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        if self._dismiss_customize_confirm(context):
            return True
        names = preset.select_change_source_names
        deck = self._scan_full_deck(context)

        self._archive_decision(self._get_screenshot(context), "select_change_source_deck", {
            "action": "deck_snapshot",
            "names": list(names),
            "deck_size": len(deck),
            "deck": [e["name"] for e in deck],
        })

        chosen = self._pick_source_by_list(names, deck)
        if chosen is None:
            logger.warning("HIF 変卡: 牌库扫描为空,安全停止")
            return self._stop_unsupported(context, "select_change_source_deck", "deck_scan_empty")

        mode = "named" if any(self._norm(n) == chosen["name"] for n in names) else "fallback_first_cell"
        logger.info(f"HIF 変卡: 源卡选定「{chosen['name']}」mode={mode}")

        # 选中定位（実機 13:34 复盘：滚动后坐标重放不可靠——回弹/偏移致复核错卡）：
        # 滚回顶部（首格卡名==deck[0] 探测验证）→ chosen≠deck[0] 时顺序点选扫描到目标
        if not self._scroll_top_verified(context, deck[0]["name"]):
            return self._stop_unsupported(context, "select_change_source_deck", "scroll_back_failed")
        if chosen["name"] != deck[0]["name"] and not self._scan_until_card(context, chosen["name"]):
            return self._stop_unsupported(context, "select_change_source_deck", "source_relocate_failed")

        self._archive_decision(self._get_screenshot(context), "select_change_source_deck", {
            "action": "pick_source", "mode": mode,
            "names": list(names), "chosen": chosen["name"],
            "deck_size": len(deck),
        })
        return self._click_change_verified(context)

    # ------------------------------------------------------------------
    # 纯逻辑（可单测）
    # ------------------------------------------------------------------

    @staticmethod
    def _norm(name: str) -> str:
        return normalize_card_name(name or "").rstrip("+")

    @classmethod
    def _pick_source_by_list(cls, names: tuple[str, ...], deck: list[dict]) -> Optional[dict]:
        """名单优先（名单序 = 优先序）→ miss 回退牌库首格（Q3 裁决）。"""
        wanted = [cls._norm(n) for n in names if n and cls._norm(n)]
        for target in wanted:
            for entry in deck:
                if entry["name"] == target:
                    return entry
        return deck[0] if deck else None

    @staticmethod
    def _dedupe_deck(entries: list[dict]) -> list[dict]:
        """滚动重叠屏去重：同名卡保留首次出现的（更靠近牌库顶部的格位）。"""
        seen: set[str] = set()
        out: list[dict] = []
        for e in entries:
            if e["name"] and e["name"] not in seen:
                seen.add(e["name"])
                out.append(e)
        return out

    # ------------------------------------------------------------------
    # 画面交互
    # ------------------------------------------------------------------

    @classmethod
    def _read_cell_name(cls, context: Context, image) -> str:
        """选中格卡名：crop 卡名带放大 2 倍 OCR → 词典归一 → 剥档位后缀。"""
        x1, y1, x2, y2 = cls.NAME_ZONE
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            return ""
        pil = Image.fromarray(crop[..., ::-1]).resize(((x2 - x1) * 2, (y2 - y1) * 2), Image.LANCZOS)
        zoomed = np.array(pil)[..., ::-1]
        detail = context.run_recognition(
            "HIFChangeCellName", zoomed,
            pipeline_override={"HIFChangeCellName": {
                "recognition": "OCR", "expected": [".*"],
                "roi": [0, 0, zoomed.shape[1], zoomed.shape[0]],
            }},
        )
        if not (detail and detail.hit):
            return ""
        name = cls._norm(detail.best_result.text)
        # 噪声过滤（実機 13:34 复盘：详情区未渲染好时 OCR 出 'D'/'0'/'5' 单字符）：
        # 卡名必须含日文（假名/汉字）且 ≥4 字，否则视为未读到
        if len(name) < 4 or not any("\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff" for ch in name):
            return ""
        return name

    def _scan_full_deck(self, context: Context) -> list[dict]:
        """逐屏逐格点选读卡名，全库收集（含滚动，Q2 裁决）→ 去重清单。

        判底（実機 2026-08-22 轮2 用户实证修正）：整屏确认模式——滚动后读完整屏
        3 行×12 格，**本屏全部非空卡名 ∈ 已见集合**才判到底。旧版「滚动后首行探针
        预判」是错的：滚动 300px 后新屏首行必然是重叠行（旧屏第三排），探针全
        命中已见即 break，新屏第二三排的新卡全部跳过（実機表现=只读一排就结束）。
        """
        entries: list[dict] = []
        for screen in range(self.MAX_SCREENS):
            for ri, y in enumerate(self.GRID_ROWS, 1):
                for ci, x in enumerate(self.GRID_COLS, 1):
                    name = self._read_cell_name_after_click(context, x, y)
                    entries.append({"screen": screen, "cell": f"s{screen}r{ri}c{ci}", "xy": [x, y], "name": name})
                    logger.debug(f"HIF 変卡扫描: s{screen}r{ri}c{ci} = {name!r}")
            if screen > 0:
                # 整屏确认：本屏非空卡名全部已在前屏见过 = 到底（重叠行不算新）
                cur = [e["name"] for e in entries if e["screen"] == screen and e["name"]]
                prior = {e["name"] for e in entries if e["screen"] < screen and e["name"]}
                new_count = sum(1 for n in cur if n not in prior)
                logger.info(f"HIF 変卡扫描: 第 {screen + 1} 屏读完,新增 {new_count}/{len(cur)} 张")
                if cur and new_count == 0:
                    logger.info(f"HIF 変卡扫描: 整屏重复,判到底(累计 {len(prior)} 张)")
                    break
            if screen < self.MAX_SCREENS - 1:
                self._swipe(context, *self.SCROLL_FROM, *self.SCROLL_TO, 300)
                time.sleep(self.ACTION_DELAY)
        return self._dedupe_deck(entries)

    def _read_cell_name_after_click(self, context: Context, x: int, y: int) -> str:
        self._click_box_center(context, [x - 24, y - 24, 48, 48], double=False)
        time.sleep(self.CELL_CLICK_DELAY)
        return self._read_cell_name(context, self._get_screenshot(context))

    def _scroll_top_verified(self, context: Context, top_name: str) -> bool:
        """滚回牌库顶部并以首格卡名==deck[0] 验证（实测反向滚动有回弹，坐标推算不可靠）。"""
        got = self._read_cell_name_after_click(context, self.GRID_COLS[0], self.GRID_ROWS[0])
        for _ in range(self.MAX_SCREENS * 2):
            if got == top_name:
                return True
            self._swipe(context, *self.SCROLL_TO, *self.SCROLL_FROM, 300)
            time.sleep(self.ACTION_DELAY)
            got = self._read_cell_name_after_click(context, self.GRID_COLS[0], self.GRID_ROWS[0])
        return got == top_name

    def _scan_until_card(self, context: Context, target: str) -> bool:
        """从当前位置逐格点选扫描直到读到目标卡（该格保持选中态），含翻屏。"""
        for _ in range(self.MAX_SCREENS):
            for y in self.GRID_ROWS:
                for x in self.GRID_COLS:
                    got = self._read_cell_name_after_click(context, x, y)
                    if got == target:
                        return True
            self._swipe(context, *self.SCROLL_FROM, *self.SCROLL_TO, 300)
            time.sleep(self.ACTION_DELAY)
        return False

    def _click_change_verified(self, context: Context) -> bool:
        """点チェンジ（按钮不亮=トラブル格不可変时顺延下一格重试，Q3 配套）。"""
        cells = [(x, y) for y in self.GRID_ROWS for x in self.GRID_COLS]
        idx = 0
        for _ in range(self.FALLBACK_MAX_TRIES):
            image = self._get_screenshot(context)
            button = self._find_text_option(context, image, ("チェンジ",), self.CHANGE_BUTTON_ROI)
            if button:
                if self._click_box_center(context, button.best_result.box, double=False):
                    time.sleep(self.ACTION_DELAY)
                    return True
            if idx + 1 >= len(cells):
                break
            idx += 1
            self._click_box_center(context, [cells[idx][0] - 24, cells[idx][1] - 24, 48, 48], double=False)
            time.sleep(self.CELL_CLICK_DELAY)
        return self._stop_unsupported(context, "select_change_source_deck", "change_button_not_found")


@AgentServer.custom_action("ProduceHIFConsultAuto")
class ProduceHIFConsultAuto(_ProduceHIFActionBase):
    """首版仅支持保留 P 点并结束咨询商店。"""

    FINISH_ROI = [530, 1000, 190, 150]
    # 相談触发的前置弹窗:支援卡事件效果(実機 2026-08-15 取证标题「サポートイベント効果」+OK 按钮 [235,1122,181,68])
    POPUP_TITLE = "サポートイベント効果"
    POPUP_TITLE_ROI = [40, 890, 400, 60]
    POPUP_OK_TAP = (325, 1156)
    POPUP_MAX_ROUNDS = 3
    # 相談商店入场动画/列表渲染需要时间(実機 2026-08-20:Flag 命中后首屏仅顶部标题,
    # 「終了」按钮晚于 Custom action 到达),整体识别带重试
    SETTLE_DELAY = 1.2
    SETTLE_ROUNDS = 3
    # 商店页说明文锚(同 ConsultFlag);点「終了」后转场窗口内 Flag 可被重复路由命中,
    # 锚消失=商店已关闭(排名转场页無終了可寻),放行让路由接管 タップして次へ(実機 2026-08-21)
    SHOP_ANCHOR_ROI = [100, 250, 520, 120]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        if preset.consult_policy_override:
            if preset.consult_policy_override not in ("finish_without_purchase",):
                return self._stop_unsupported(context, "consult_shop", f"consult_policy_override_not_supported: {preset.consult_policy_override}")
        elif preset.consult_policy != "finish_without_purchase":
            return self._stop_unsupported(context, "consult_shop", "consult_policy_not_supported")

        # 先关掉支援卡事件效果弹窗(可能连续多个),否则「終了」被遮挡找不到;
        # 整体带重试:入场动画期间列表/按钮未渲染时等待再试
        finish_button = None
        for attempt in range(self.SETTLE_ROUNDS):
            for _ in range(self.POPUP_MAX_ROUNDS):
                image = self._get_screenshot(context)
                popup = self._find_text_option(context, image, (self.POPUP_TITLE,), self.POPUP_TITLE_ROI)
                if not popup:
                    break
                logger.info("HIF 相談:关闭支援卡事件效果弹窗")
                self._tap(context, *self.POPUP_OK_TAP)
                time.sleep(self.ACTION_DELAY)

            image = self._get_screenshot(context)
            if not self._find_text_option(context, image, ("Pポイントと交換",), self.SHOP_ANCHOR_ROI):
                logger.info("HIF 相談: 商店锚已消失(終了已点击转场中?),放行")
                return True
            finish_button = self._find_text_option(context, image, ("終了",), self.FINISH_ROI)
            if finish_button:
                break
            if attempt < self.SETTLE_ROUNDS - 1:
                logger.info(f"HIF 相談:「終了」未见(第{attempt + 1}轮),等待商店渲染")
                time.sleep(self.SETTLE_DELAY)

        if not finish_button:
            return self._stop_unsupported(context, "consult_shop", "finish_button_not_found")
        if not self._click_box_center(context, finish_button.best_result.box, double=False):
            return self._stop_unsupported(context, "consult_shop", "finish_button_click_failed")
        self._archive_decision(image, "consult_shop", {
            "action": "finish_without_purchase", "policy": preset.consult_policy_override or preset.consult_policy,
        })
        return True


@AgentServer.custom_action("ProduceChooseHIFSPCardAuto")
class ProduceChooseHIFSPCardAuto(_ProduceHIFActionBase):
    """レッスン終了時効果选择页(4 张全宽卡,疑为 Pドリンク 选择,池 27 种)。

    点卡即执行无确认按钮(実機 2026-08-14),不能逐张点选;
    改为 OCR 页面文字行做关键词评分选最高分行点击,无文字可读时回退点第一张。
    页面文字布局[待実機校准]。
    """

    OPTION_ROI = [40, 600, 660, 560]
    FIRST_CARD_BOX = [360, 660, 1, 1]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        table = load_keyword_tables(overrides=build_gui_keyword_overrides(preset))[preset.preference]
        image = self._get_screenshot(context)
        reco_detail = self._run_ocr(context, image, "ProduceRecognitionHIFSPCardText", [".*"], self.OPTION_ROI)

        target_box = None
        line_records: list[dict] = []
        if reco_detail and reco_detail.all_results:
            lines = [
                item
                for item in reco_detail.all_results
                if item.box[3] > 20 and re.search(r"[ぁ-んァ-ヶ一-龯]", item.text)
            ]
            if lines:
                scored = [(item, *table.score_detail(item.text)) for item in lines]
                best_item, best_score, best_breakdown = max(scored, key=lambda pair: pair[1])
                detail_str = ",".join(f"{kw}{value:+g}" for kw, value in best_breakdown) or "无命中"
                logger.info(f"HIF SP效果卡: 最高分 {best_score:.0f} [{detail_str}]「{best_item.text[:40]}」")
                target_box = best_item.box
                line_records = [
                    {"text": item.text, "score": score, "breakdown": breakdown}
                    for item, score, breakdown in scored
                ]

        fallback = target_box is None
        if fallback:
            logger.info("HIF SP效果卡: 无文字可读或全无命中,回退点击第一张")
            target_box = self.FIRST_CARD_BOX
        if not self._click_box_center(context, target_box, double=False):
            return self._stop_unsupported(context, "hif_sp_card_select", "card_click_failed")
        time.sleep(self.ACTION_DELAY)
        self._archive_decision(image, "hif_sp_card_select", {
            "action": "pick_line",
            "lines": line_records,
            "chosen": "first_fallback" if fallback else "best_score_line",
            "preference": preset.preference,
            "evidence_empty": fallback or not line_records,
        })
        return True


@AgentServer.custom_action("ProduceChooseHIFDrinkOverflowAuto")
class ProduceChooseHIFDrinkOverflowAuto(_ProduceHIFActionBase):
    """P 饮料持有上限取舍:色扫定位勾选框,补勾未选项至「あとN個」归零后点「残す」。

    実機 2026-08-15(Day5)取证:勾选框中心 x≈620-640,橙色实心(255,118,0)=已勾、
    灰色(201,204,204)=未勾;接收区/手持区行 y 随获得饮料数变化,固定行列表不可靠
    (Day5 失败根因:y=305 标题行点空后 stagnant_taps 跨行累积毒死全部后续行)。
    """

    REMAIN_ROI = [260, 1180, 200, 50]
    KEEP_ROI = [210, 1090, 300, 110]
    CHECKBOX_SCAN_X = (560, 700)
    CHECKBOX_SCAN_Y = (250, 1160)
    CHECKBOX_MIN_RUN = 10  # 单行特征色像素数下限
    CHECKBOX_MIN_HEIGHT = 20  # 色块高度下限(px)
    SCROLL_ROUNDS = 2

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        first_image = self._get_screenshot(context)
        remain = self._read_digits_text(context, first_image)
        if remain is None:
            return self._stop_unsupported(context, "hif_drink_overflow", "remain_counter_not_found")
        initial_remain = remain

        for scroll_round in range(self.SCROLL_ROUNDS):
            image = self._get_screenshot(context)
            boxes = self._find_checkboxes(image)
            pending = [(x, y) for x, y, checked in boxes if not checked]
            logger.info(f"HIF 饮料上限:勾选框 {len(boxes)} 个(未勾 {len(pending)}),remain={remain},第 {scroll_round + 1} 轮")
            stagnant = 0
            while remain > 0 and pending and stagnant < 2:
                x, y = pending.pop(0)
                self._tap(context, x, y)
                time.sleep(self.ACTION_DELAY)
                new_remain = self._read_digits_text(context, self._get_screenshot(context))
                if new_remain is None:
                    return self._stop_unsupported(context, "hif_drink_overflow", "remain_counter_lost_after_tap")
                if new_remain > remain:
                    # 颜色误判点中已勾框:撤销勾选并放弃该框
                    self._tap(context, x, y)
                    time.sleep(self.ACTION_DELAY)
                    stagnant += 1
                    continue
                if new_remain == remain:
                    stagnant += 1
                    continue
                remain = new_remain
                stagnant = 0
            if remain == 0:
                break
            if scroll_round + 1 < self.SCROLL_ROUNDS:
                self._swipe(context, 360, 900, 360, 500, 300)
                time.sleep(self.ACTION_DELAY)

        if remain != 0:
            return self._stop_unsupported(context, "hif_drink_overflow", f"pick_converge_failed: remain={remain}")

        image = self._get_screenshot(context)
        keep = self._find_text_option(context, image, ("残す",), self.KEEP_ROI)
        if not keep:
            return self._stop_unsupported(context, "hif_drink_overflow", "keep_button_not_found")
        if not self._click_box_center(context, keep.best_result.box, double=False):
            return self._stop_unsupported(context, "hif_drink_overflow", "keep_button_click_failed")
        logger.success("HIF 饮料上限:取舍完成(remain=0,已提交残す)")
        self._archive_decision(first_image, "hif_drink_overflow", {
            "action": "keep_submit", "initial_remain": initial_remain, "final_remain": remain,
            "checkboxes": [{"x": x, "y": y, "checked": c} for x, y, c in boxes],
        })
        time.sleep(self.ACTION_DELAY)
        return True

    def _find_checkboxes(self, image) -> list[tuple[int, int, bool]]:
        """色扫勾选框,返回 [(x_center, y_center, checked)]。

        对称色条件不依赖通道序(maafw 截图可能 BGR):
        已勾=橙 (255,118,0) → R/B 一高一中差、G 中;未勾=灰 (201,204,204) → 三通道近等且 185-225。
        """
        img = Image.fromarray(image)
        px = img.load()
        x0, x1 = self.CHECKBOX_SCAN_X
        y0, y1 = self.CHECKBOX_SCAN_Y
        runs = []  # (y, checked, xs)
        for y in range(y0, min(y1, img.height)):
            checked_xs, unchecked_xs = [], []
            for x in range(x0, min(x1, img.width)):
                r, g, b = px[x, y][:3]
                if abs(r - b) > 90 and 90 <= g <= 160 and max(r, b) > 240:
                    checked_xs.append(x)
                elif abs(r - b) <= 20 and all(185 <= v <= 225 for v in (r, g, b)):
                    unchecked_xs.append(x)
            if len(checked_xs) >= self.CHECKBOX_MIN_RUN:
                runs.append((y, True, checked_xs))
            elif len(unchecked_xs) >= self.CHECKBOX_MIN_RUN:
                runs.append((y, False, unchecked_xs))
        # 相邻同色行聚类成块,取块中心的 x 均值
        boxes, cur = [], None
        for y, checked, xs in runs:
            if cur and cur["checked"] == checked and y - cur["y2"] <= 3:
                cur["y2"] = y
                cur["xs"] += xs
            else:
                if cur and cur["y2"] - cur["y1"] >= self.CHECKBOX_MIN_HEIGHT:
                    boxes.append((sum(cur["xs"]) // len(cur["xs"]), (cur["y1"] + cur["y2"]) // 2, cur["checked"]))
                cur = {"checked": checked, "y1": y, "y2": y, "xs": list(xs)}
        if cur and cur["y2"] - cur["y1"] >= self.CHECKBOX_MIN_HEIGHT:
            boxes.append((sum(cur["xs"]) // len(cur["xs"]), (cur["y1"] + cur["y2"]) // 2, cur["checked"]))
        return boxes

    def _read_digits_text(self, context: Context, image) -> Optional[int]:
        reco_detail = self._run_ocr(context, image, "ProduceRecognitionHIFDrinkRemain", [".*あと[0-9０-９]+個.*"], self.REMAIN_ROI)
        if not (reco_detail and reco_detail.hit):
            return None
        digits = "".join(char for char in reco_detail.best_result.text if char.isdigit())
        return int(digits) if digits else None


@AgentServer.custom_action("ProduceHIFSelectChangeDoneAuto")
class ProduceHIFSelectChangeDoneAuto(_ProduceHIFActionBase):
    """変卡/強化演出提示页:点空白推进;仅真変卡流程(在途标记)记决策日志。

    「強化しました」锚同样命中日程收尾的支援卡随机强化演出页(角色对话+随机卡強化)——
    该类页面不记日志以免混淆,静默推进即可(用户定案 2026-08-15)。
    注意「戻る」按钮是回退本次強化/チェンジ 的撤销键,绝不可点(用户确认 2026-08-15);
    空白点取横幅下方区(実機 2026-08-15 逐位试探:卡面 (360,640)/横幅行 (360,830) 均无效,(360,1000) 有效)。
    """

    BLANK_TAP = (360, 1000)

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        is_real_change = _ProduceHIFActionBase._read_session_state().get(_ProduceHIFActionBase.SELECT_CHANGE_FLAG)
        if is_real_change:
            _ProduceHIFActionBase._write_session_state({_ProduceHIFActionBase.SELECT_CHANGE_FLAG: False})
        logger.info(f"HIF 変卡完成:点空白 ({self.BLANK_TAP[0]},{self.BLANK_TAP[1]}) 推进" + ("" if is_real_change else "(非変卡流程,不记日志)"))
        if is_real_change:
            self._archive_decision(self._get_screenshot(context), "select_change_done", {
                "action": "blank_tap", "tap": list(self.BLANK_TAP),
            })
        self._tap(context, *self.BLANK_TAP)
        time.sleep(self.ACTION_DELAY)
        return True


@AgentServer.custom_action("ProduceHIFChooseIdolAuto")
class ProduceHIFChooseIdolAuto(_ProduceHIFActionBase):
    """HIF 偶像选择页(步骤1)：校验当前选中偶像与预设一致后点击「プロデュース開始」。"""

    # ROI 实机校准自 MuMu 720x1280 偶像选择页(MaaFW OCR box: True End y76-96/名字 y154-211/卡名 y119-150)
    TRUE_END_ROI = [430, 70, 266, 35]
    IDOL_NAME_ROI_TRUE_END = [440, 140, 280, 80]
    IDOL_NAME_ROI_DEFAULT = [400, 98, 320, 64]
    SONG_NAME_ROI_TRUE_END = [380, 112, 320, 42]
    SONG_NAME_ROI_DEFAULT = [340, 60, 380, 45]
    NEXT_BUTTON_ROI = [150, 1000, 420, 200]
    IDOL_SIMILARITY_THRESHOLD = 0.9
    SONG_SIMILARITY_THRESHOLD = 0.7
    # 步骤1/2 页顶共有的步骤条锚;action 重试期间锚消失=页面已推进(培育已开始),放行交回路由
    STEP_BAR_ROI = [0, 0, 720, 80]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        # MaaFW 对未定义 custom_action_param 的节点传 "null" 字符串,loads 结果需兜底为空 dict
        params: Dict[str, Any] = json.loads(argv.custom_action_param) if argv.custom_action_param else {}
        if not isinstance(params, dict):
            params = {}
        expected_idol = params.get("idol_name", "")
        expected_song = params.get("song_name", "")

        image = self._get_screenshot(context)
        true_end_detail = self._run_ocr(context, image, "ProduceHIFIdolTrueEnd", ["True", "End"], self.TRUE_END_ROI)
        has_true_end = bool(true_end_detail and true_end_detail.hit)
        name_roi = self.IDOL_NAME_ROI_TRUE_END if has_true_end else self.IDOL_NAME_ROI_DEFAULT

        recognized_name = self._read_text(context, image, "ProduceHIFIdolName", name_roi)
        logger.info(f"HIF 偶像选择: true_end={has_true_end}, 当前偶像={recognized_name or '未识别'}")

        if expected_idol and recognized_name:
            similarity = SequenceMatcher(None, recognized_name, expected_idol).ratio()
            if similarity < self.IDOL_SIMILARITY_THRESHOLD:
                return self._stop_unsupported(
                    context, "hif_idol_select", f"idol_mismatch: got={recognized_name}, want={expected_idol}, ratio={similarity:.2f}"
                )

        if expected_song and recognized_name:
            song_roi = self.SONG_NAME_ROI_TRUE_END if has_true_end else self.SONG_NAME_ROI_DEFAULT
            recognized_song = self._read_text(context, image, "ProduceHIFIdolSong", song_roi)
            if recognized_song:
                similarity = SequenceMatcher(None, recognized_song, expected_song).ratio()
                if similarity < self.SONG_SIMILARITY_THRESHOLD:
                    return self._stop_unsupported(
                        context, "hif_idol_select", f"song_mismatch: got={recognized_song}, want={expected_song}, ratio={similarity:.2f}"
                    )

        # 底部中央大按钮:普通偶像页为「プロデュース開始」(box 约 [247,1059,225,33]);
        # True End 姫崎莉波页(実機 2026-08-15)首屏为「次へ」(box [351,1074,53,32]),按序找两者。
        # miss 时等待重截(防转场/LOADING 窗口,実機 2026-08-21);步骤条也消失说明已离开选择流程,
        # 放行让 PrepRoot 路由接管(培育开始加载页無锚可依)
        next_button = None
        for attempt in range(3):
            image = self._get_screenshot(context)
            if not self._find_text_option(context, image, ("アイドル選択",), self.STEP_BAR_ROI):
                logger.info("HIF 偶像选择: 步骤条已消失(页面已推进),放行")
                return True
            next_button = self._find_text_option(context, image, ("プロデュース開始", "次へ"), self.NEXT_BUTTON_ROI)
            if next_button:
                break
            time.sleep(self.ACTION_DELAY)
        if not next_button:
            return self._stop_unsupported(context, "hif_idol_select", "next_button_not_found")
        if not self._click_box_center(context, next_button.best_result.box, double=False):
            return self._stop_unsupported(context, "hif_idol_select", "next_button_click_failed")
        return True

    def _read_text(self, context: Context, image, name: str, roi: list[int]) -> str:
        reco_detail = self._run_ocr(context, image, name, [".*"], roi)
        if not (reco_detail and reco_detail.hit):
            return ""
        return "".join(item.text for item in reco_detail.all_results).replace(" ", "")


@AgentServer.custom_action("ProduceHIFStartConfirmAuto")
class ProduceHIFStartConfirmAuto(_ProduceHIFActionBase):
    """HIF 開始確認页(步骤2)：直接以页面默认编成点击「プロデュース開始」开始培育。"""

    START_BUTTON_ROI = [150, 1000, 420, 200]
    # 步骤2 独有锚(步骤1 的「選抜試験メモリー」无「選択中の」前缀,不会误命中)
    ANCHOR_ROI = [0, 530, 720, 80]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        # miss 时等待重截(防转场/LOADING 窗口);锚消失=培育已被前序点击启动(加载页無锚),
        # 放行交回路由,Day1 日程由 ScheduleRoot 接管(実機 2026-08-21)
        start_button = None
        for attempt in range(3):
            image = self._get_screenshot(context)
            if not self._find_text_option(context, image, ("選択中の選抜試験",), self.ANCHOR_ROI):
                logger.info("HIF 開始確認: 锚已消失(培育已开始?),放行")
                return True
            start_button = self._find_text_option(context, image, ("プロデュース開始",), self.START_BUTTON_ROI)
            if start_button:
                break
            time.sleep(self.ACTION_DELAY)
        if not start_button:
            return self._stop_unsupported(context, "hif_start_confirm", "start_button_not_found")
        # 変卡源卡名单启动校验（grill Q9 2026-08-21）：非法名/トラブル名落盘告警不阻断
        preset = self._get_preset(argv)
        source_warnings = validate_select_change_source_names(
            preset.select_change_source_names, build_card_name_dict()
        )
        if source_warnings:
            logger.warning(f"HIF 開始確認: 変卡源卡名单告警 {source_warnings}")
            self._archive_decision(image, "hif_start_confirm", {
                "action": "source_names_warning", "warnings": source_warnings,
                "names": list(preset.select_change_source_names),
            })
        if not self._click_box_center(context, start_button.best_result.box, double=False):
            return self._stop_unsupported(context, "hif_start_confirm", "start_button_click_failed")
        logger.success("HIF 開始確認：以默认编成开始培育")
        time.sleep(self.ACTION_DELAY)
        return True


@AgentServer.custom_action("ProduceHIFChooseFinalModeAuto")
class ProduceHIFChooseFinalModeAuto(_ProduceHIFActionBase):
    """在已识别的 HIF 入口按预设进入本战模式。"""

    FINAL_MODE_BUTTON = [360, 824, 360, 171]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        if self._get_preset(argv).entry_mode != "finals":
            return self._stop_unsupported(context, "hif_mode_select", "entry_mode_not_supported")
        if not self._click_box_center(context, self.FINAL_MODE_BUTTON, double=False):
            return self._stop_unsupported(context, "hif_mode_select", "final_mode_click_failed")
        logger.success("HIF 入口：按预设选择本战模式")
        time.sleep(self.ACTION_DELAY)
        return True


@AgentServer.custom_action("ProduceHIFPDrinkObtainedAuto")
class ProduceHIFPDrinkObtainedAuto(_ProduceHIFActionBase):
    """P 饮料获得弹窗：读瓶名→库匹配（match_drink_name）落盘 JSONL→点弹窗推进。

    実機 2026-08-21 取证：饮料名大字行 y838-900（drinks.json 28 名称池可命中），
    效果文本随饮料变。识别锚由 Flag 侧 expected 名称池承担，本 action 读名称行
    OCR 落盘后点名称行中心推进。
    """

    NAME_ROI = [180, 810, 400, 110]

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        image = self._get_screenshot(context)
        detail = self._run_ocr(context, image, "HIFPDrinkObtainedName", [".*"], self.NAME_ROI)
        raw = detail.best_result.text.strip() if (detail and detail.hit) else ""
        name, record = match_drink_name(raw) if raw else (None, None)
        if raw and name is None:
            logger.warning(f"HIF P饮料获得: 名称匹配失败 raw={raw!r}")
        self._archive_decision(image, "p_drink_obtained", {
            "action": "obtain",
            "raw": raw or None,
            "matched": name,
            "effects": (record or {}).get("effects") if record else None,
            "evidence_empty": not raw,
        })
        box = detail.best_result.box if (detail and detail.hit) else [340, 850, 40, 60]
        self._click_box_center(context, box, double=False)
        time.sleep(self.ACTION_DELAY)
        return True


@AgentServer.custom_action("ProduceHIFIntervalAuto")
class ProduceHIFIntervalAuto(_ProduceHIFActionBase):
    """Interval 页推进：首版策略=直接終了（P 点消费探索轮补，goal 裁决放开但不强制）。

    実機 2026-08-20 取证（round2-settlement-ui-inventory §4）：終了按钮
    [629,1064]→(663,1082)，**需点 1-2 次**（首次偶发无响应）；点击后进 R2 優勝条件页。
    流转验证：Interval 锚（提示文）消失=終了已生效；锚在=再点（容点 2 次）后放行
    交回路由（防止转场窗口内 Flag 重复命中在未渲染页面上 stop）。
    """

    FINISH_ROI = [560, 1020, 140, 90]
    FINISH_TAP = (663, 1082)
    ANCHOR_TEXT = ("Pポイントで利用する",)
    ANCHOR_ROI = [60, 260, 600, 120]
    MAX_ROUNDS = 4

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        clicked = 0
        for _ in range(self.MAX_ROUNDS):
            image = self._get_screenshot(context)
            if not self._find_text_option(context, image, self.ANCHOR_TEXT, self.ANCHOR_ROI):
                logger.info("HIF Interval: 锚已消失(終了已生效/页面已推进),放行")
                # 提前 return 前必须 archive(P0-1:早期版本只在循环耗尽才记录,
                # 锚消失放行路径零记录,决策日志缺此决策点)
                self._archive_decision(image, "hif_interval", {
                    "action": "finish_interval", "clicked": clicked, "early_exit": "anchor_gone",
                })
                return True
            finish = self._find_text_option(context, image, ("終了",), self.FINISH_ROI)
            if not finish:
                # 按钮未渲染时等待重试;多轮仍无按钮但锚在=页面异常,安全停止
                time.sleep(self.ACTION_DELAY)
                image = self._get_screenshot(context)
                finish = self._find_text_option(context, image, ("終了",), self.FINISH_ROI)
                if not finish:
                    if clicked:
                        self._archive_decision(image, "hif_interval", {
                            "action": "finish_interval", "clicked": clicked, "early_exit": "button_gone",
                        })
                        return True  # 点过終了且按钮已消失,视为推进中放行
                    return self._stop_unsupported(context, "hif_interval", "finish_button_not_found")
            self._click_box_center(context, finish.best_result.box, double=False)
            clicked += 1
            time.sleep(self.ACTION_DELAY)
        self._archive_decision(self._get_screenshot(context), "hif_interval", {
            "action": "finish_interval", "clicked": clicked,
        })
        return True


@AgentServer.custom_action("ProduceHIFRetryConfirmAuto")
class ProduceHIFRetryConfirmAuto(_ProduceHIFActionBase):
    """再挑戦確認弹窗（R2 敗退后点次へ出現）：选プロデュース終了进入正常结算链。

    goal 裁决（2026-08-21）：一轮终点=完成整局培育（R2→结算→メモリー→回主页面），
    敗退不是故障；此弹窗选「プロデュース終了」=接受结果进结算，非ギブアップ中断
    （黑名单的「中途放弃」指培育进行中主动中断）。「再挑戦」探索轮放开但默认不走。
    実機坐标（inventory §7.2）：×プロデュース終了 [87,1102]≈(210,1155)；
    再挑戦 [471,1133] 禁点。弹窗文案「再挑戦が可能ですが本当に終了しますか?」。
    """

    END_TAP = (200, 1140)  # vision 実測 2026-08-22 轮3:hitbox 内缩,旧(216,1154)连点 8 次不中
    ANCHOR_TEXT = ("再挑戦が可能", "本当に終了")
    ANCHOR_ROI = [40, 700, 640, 350]  # 弹窗 y 随内容浮动(実機 y946 超 180 高,轮4 miss)
    MAX_ROUNDS = 8
    SETTLE_DELAY = 2.0  # 弹窗入场动画内点击会丢失(実機 2026-08-22 轮0/轮2:段内连点
    # 未生效两次,手动同坐标单点即中——IPC 点击丢失高发位,重试上限提到 8)

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        # 首轮锚命中后先等入场动画稳定再点
        time.sleep(self.SETTLE_DELAY)
        clicked = 0
        for _ in range(self.MAX_ROUNDS):
            image = self._get_screenshot(context)
            if not self._find_text_option(context, image, self.ANCHOR_TEXT, self.ANCHOR_ROI):
                logger.info("HIF 再挑戦確認: 弹窗已消失(終了已生效),放行")
                # 提前 return 前必须 archive(P0-1:锚消失放行路径原零记录)
                self._archive_decision(image, "hif_retry_confirm", {
                    "action": "produce_end", "clicked": clicked, "early_exit": "anchor_gone",
                })
                return True
            self._tap(context, *self.END_TAP)
            clicked += 1
            time.sleep(self.ACTION_DELAY)
        self._archive_decision(self._get_screenshot(context), "hif_retry_confirm", {
            "action": "produce_end", "clicked": clicked,
        })
        return True


@AgentServer.custom_action("ProduceHIFMemoryDetailNextAuto")
class ProduceHIFMemoryDetailNextAuto(_ProduceHIFActionBase):
    """メモリー詳細页推进（正式确认页→次へ）。

    実機 2026-08-22 轮0 三个发现：
    - 正式確認页（メモリー変換「あとN回可能」+再生成+次へ+獲得可能スキルカード）的
      次へ用固定坐标 (360,1156) 点击会**误点进メモリー浏览詳細页**（全屏アビリティ
      页，无次へ、<< 点击无效）——改为 OCR 锚定「次へ」box 精确点击；
    - 浏览詳細页唯一可靠出口=Android BACK 键（adb keyevent 4 実証生效，<< 按钮无效）；
    - BACK 从浏览页回正式確認页（再 BACK 会到メモリー一覧页——多按会漂移，控次数）。
    """

    DETAIL_ANCHOR = ("メモリー変換", "獲得可能")
    DETAIL_ANCHOR_ROI = [20, 80, 680, 400]
    BROWSER_MARK = "専用アビリティ"
    NEXT_ROI = [240, 1080, 240, 130]
    KEY_BACK = 4
    MAX_ROUNDS = 4

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        for _ in range(self.MAX_ROUNDS):
            image = self._get_screenshot(context)
            if self._find_text_option(context, image, self.DETAIL_ANCHOR, self.DETAIL_ANCHOR_ROI):
                nxt = self._find_text_option(context, image, ("次へ",), self.NEXT_ROI)
                if not nxt:
                    return self._stop_unsupported(context, "hif_memory_detail", "next_button_not_found")
                self._click_box_center(context, nxt.best_result.box, double=False)
                time.sleep(self.ACTION_DELAY)
                verify = self._get_screenshot(context)
                if not self._find_text_option(context, verify, self.DETAIL_ANCHOR, self.DETAIL_ANCHOR_ROI):
                    logger.success("HIF メモリー詳細: 次へ已生效")
                    return True
                logger.info("HIF メモリー詳細: 次へ点击后锚仍在(误入浏览页?),BACK 自愈")
            # 非正式页（浏览詳細页/其他）：BACK 一次回正式確認页
            browser = self._find_text_option(context, image, (self.BROWSER_MARK,), [0, 0, 720, 400])
            if browser:
                self._key(context, self.KEY_BACK)
                time.sleep(self.ACTION_DELAY)
                continue
            # 既非正式页也无浏览页标记：放行交回路由
            return True
        return self._stop_unsupported(context, "hif_memory_detail", "memory_detail_loop_limit")


@AgentServer.custom_action("ProduceHIFFinalModeAuto")
class ProduceHIFFinalModeAuto(_ProduceHIFActionBase):
    """HIF 活动主页→本戦 tab 切换（带验证重试）。

    実機 2026-08-22 轮1/2：管线 Click 点击本戦 tab 偶发静默丢失（adb 入场动画
    窗口），画面停在選抜視図致段退出。改为：OCR 锚定 tab box 点击→验证
    「1.アイドル選択」步骤条出现（本戦視図特征）→未生效原坐标重试 ≤3。
    """

    TAB_ROI = [140, 850, 500, 80]
    VERIFY_ROI = [0, 0, 720, 130]
    MAX_ROUNDS = 3

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        if preset.entry_mode != "finals":
            return self._stop_unsupported(context, "hif_mode_select", "entry_mode_not_supported")
        for _ in range(self.MAX_ROUNDS):
            image = self._get_screenshot(context)
            tab = self._find_text_option(context, image, ("本戦",), self.TAB_ROI)
            if not tab:
                # tab 已不可寻+步骤条在=已切成功（前次点击生效）
                if self._find_text_option(context, image, ("アイドル選択",), self.VERIFY_ROI):
                    logger.success("HIF 入口：本戦視図已切换")
                    return True
                return self._stop_unsupported(context, "hif_mode_select", "final_mode_tab_not_found")
            self._click_box_center(context, tab.best_result.box, double=False)
            time.sleep(self.ACTION_DELAY)
            verify = self._get_screenshot(context)
            if self._find_text_option(context, verify, ("アイドル選択",), self.VERIFY_ROI):
                logger.success("HIF 入口：按预设选择本戦模式")
                return True
            logger.info("HIF 入口：本戦 tab 点击未生效，重试")
        return self._stop_unsupported(context, "hif_mode_select", "final_mode_click_failed")


@AgentServer.custom_action("ProduceHIFGuardedTapAuto")
class ProduceHIFGuardedTapAuto(_ProduceHIFActionBase):
    """泛锚+空白点击的守卫推进（2026-08-22 轮2 grill 裁决）。

    死循环模式（実機三例：ItemGain「獲得」/GiftTalk「差し入れ」/本戦 tab）：泛词锚
    在同类页面残留命中+空白点击无效+[JumpBack] 回环永不清 timeout=无限空转不报错。
    本 action:锚验证→指纹记录→点击→验证(锚消失或画面变化)=成功;连续 N 次无变化
    return False 让节点失败交回轮询/on_error(段退重估,好过静默空转)。
    param: {anchor_expected:[...], anchor_roi:[x,y,w,h], tap:[x,y]}
    """

    MAX_TRIES = 3
    VERIFY_DELAY = 1.2

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        try:
            params = json.loads(argv.custom_action_param) if argv.custom_action_param else {}
        except ValueError:
            params = {}
        # anchor_expected 约定传字面短语(_find_text_option 内 re.escape+包装);若从
        # recognition.expected 复制来带 .* 前后缀则剥离,防双重转义死 pattern
        # (実機 2026-08-22 轮8 #49:GiftTalkBlank 传 ".*差し入れ.*" → 匹配字面
        #  ".*差し入れ.*" → 进门恒 miss → return False 段退)
        expected = tuple(
            p[2:-2] if len(p) > 4 and p.startswith(".*") and p.endswith(".*") else p
            for p in (params.get("anchor_expected") or [".*"])
        )
        roi = params.get("anchor_roi") or [0, 0, 720, 1280]
        tap = params.get("tap") or [360, 640]
        for attempt in range(self.MAX_TRIES):
            image = self._get_screenshot(context)
            if not self._find_text_option(context, image, expected, roi):
                if attempt > 0:
                    logger.success("守卫点击: 锚已消失(前次点击已推进)")
                    return True
                return False  # 进门即无锚=页面已过(其他锚会接管),失败交回轮询
            before = self._fingerprint(image)
            self._tap(context, *tap)
            time.sleep(self.VERIFY_DELAY)
            after_image = self._get_screenshot(context)
            after_fp = self._fingerprint(after_image)
            anchor_gone = not self._find_text_option(context, after_image, expected, roi)
            if anchor_gone or (after_fp and after_fp != before):
                logger.info(f"守卫点击: 第 {attempt + 1} 次点击推进成功(anchor_gone={anchor_gone})")
                return True
            logger.info(f"守卫点击: 第 {attempt + 1} 次点击画面无变化,重试")
        logger.warning("守卫点击: 连续无变化,return False 交回路由(防死循环)")
        return False


@AgentServer.custom_action("ProduceHIFRewardPageNextAuto")
class ProduceHIFRewardPageNextAuto(_ProduceHIFActionBase):
    """HIF 報酬序列推进（実機 2026-08-22 对照实验定案：非坐标错、非连点——
    報酬是**同构子页序列**(獲得アイテム→アチーブメント進捗→…),单点即翻一页;
    中间子页无「HIF報酬/履歴」词致锚 miss 段退=「卡死」表象)。

    策略:循环「OCR 找次へ→点→2s」,直到次へ消失(序列尽,交回路由接広告/主页),
    ≤6 页防失控。
    """

    NEXT_ROI = [200, 1080, 360, 160]
    NEXT_TEMPLATE = "autodev/hif_next_button.png"  # 次へ橙色胶囊模板(2026-08-22 裁,OCR 拆词不稳改模板)
    MAX_PAGES = 6
    TAP_INTERVAL = 2.0

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        # 入场稳定(実機 2026-08-22 轮3:段启动后页面入场动画窗口内 agent 点击静默丢失,
        # 手动同坐标即中——同 RetryConfirm SETTLE 模式)
        time.sleep(2.0)
        for page in range(self.MAX_PAGES):
            image = self._get_screenshot(context)
            # 模板优先(按钮固定图像,不受 OCR 拆词/混读影响);模板 miss 再 OCR 退路
            detail = self._run_template(context, image, "HIFRewardNextBtn", self.NEXT_TEMPLATE, self.NEXT_ROI, threshold=0.85)
            box = detail.best_result.box if (detail and detail.hit) else None
            if box is None:
                nxt = self._find_text_option(context, image, ("次へ",), self.NEXT_ROI)
                box = nxt.best_result.box if nxt else None
            if box is None:
                logger.success(f"HIF 報酬序列: 次へ消失(序列尽,共推 {page} 页),交回路由")
                return True
            # vision 実測 2026-08-22 轮3:OCR/小模板 box 只是文字区,按钮 pill 几何中心
            # 在文字区下方 ~21px——固定按钮几何中心点击,box 仅作存在判定
            self._tap(context, 360, 1180)
            time.sleep(self.TAP_INTERVAL)
        logger.info("HIF 報酬序列: 达页数上限,放行交回路由")
        return True


@AgentServer.custom_action("ProduceHIFRound1Observe")
class ProduceHIFRound1Observe(_ProduceHIFActionBase):
    """记录 Round1 初始手牌，首版不执行出牌。"""

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        if preset.round1_mode != "observe_and_stop":
            return self._stop_unsupported(context, "round1_initial", "round1_mode_not_supported")

        hand = ExamStateReader.from_context(context).read_hand()
        logger.success(
            "HIF 已到达 Round1："
            f"good_condition_cards={hand.good_condition_card_count}, "
            f"shizen={hand.has_shizen_no_miryoku}, oneesan={hand.has_oneesan_no_kankaku}, "
            f"card_names={list(hand.card_names) or '未读到'}"
        )
        self._archive_static(context, "round1_initial", {
            "action": "observe",
            "good_condition_cards": hand.good_condition_card_count,
            "shizen": hand.has_shizen_no_miryoku,
            "oneesan": hand.has_oneesan_no_kankaku,
            "card_names": list(hand.card_names),
            "evidence_empty": not hand.card_names,
        })
        return True


@AgentServer.custom_action("ProduceHIFRound1Play")
class ProduceHIFRound1Play(_ProduceHIFActionBase):
    """Round1 出牌执行（Phase 2 单 action 大包，Q11 裁决架构）。

    実機取证 2026-08-21（debug/autodev/round1/session-evidence.jsonl）：
    - 出牌交互：点卡 → SELECT 确认（按钮跟随选中卡，x∈[80,720] 漂移）→ 结算动画
    - 回合推进：出牌数尽 or 手牌空 → 自动转场（<2s），画面残りターン递减
    - 再演：右上「N回」剩余池（お姉さん打出重置 4）
    - 好調/集中：状态带行位置随 buff 增减重排，须图标模板定行（Q6 画面优先）
    - 山札张数画面不可读 → deck_size 走 session 自维护
    - flow 回合内轮换（Vi/Da/Vo），动画期 +10000% 峰值，须等稳定值

    循环内每步失败按 Q12 处理：原坐标重试 ≤2 → UnknownStop；
    USE_P_DRINK 一律拦截只记录（Q9；瓶位语义 A5 未定案，禁猜测性点击）。
    残りターン=0 时 return True 交回 pipeline 出口路由（結果页→TapNext→順位→Interval）。
    """

    TOTAL_TURNS = 9
    # 実機校准 ROI（720×1280，Phase 0 取证；勿用预估占位值覆盖）
    ROI_TURN = [20, 55, 100, 60]        # 残りターン数值（実機 2026-08-22 轮1:两位数 12 box[29,66,72,47]
    # 宽于一位数,原 [35,60,55,55] 右界截断致 R2 恒读空 turn_counter_unreadable;杂讯 M/• 靠整数提取跳过）
    ROI_STAMINA = [555, 200, 120, 60]  # 体力（全屏 OCR 曾把 29 误读 0，勿缩小）
    ROI_FLOW_NAME = [90, 45, 145, 42]  # flow 分带-日文名行（grill R1-Q3）
    ROI_FLOW_NUM = [95, 75, 135, 52]   # flow 分带-百分数行
    ROI_TOTAL_SCORE = [350, 110, 180, 60]  # 右上総分（probe 2609 実測）
    ROI_REPRISE = [550, 240, 170, 60]  # 右上「N回」——実機复核实为 P item 触发剩余（旧 reprise 源，双读落盘中）
    ROI_SELECT = [80, 1080, 640, 70]   # SELECT 确认按钮（跟随选中卡漂移）
    CLICK_SKIP = (660, 800)            # SKIP 文字锚 [636,786,54,30] 中心（绿心+2 回体）
    ROI_BUFF_BAND = [0, 230, 140, 420]  # 状态带（好調/絶好調/集中图标模板定行）
    TPL_GOOD = "autodev/hif_buff_good_condition.png"
    TPL_CONC = "autodev/hif_buff_concentration.png"

    SETTLE_DELAY = 3.5        # 出牌结算动画等待（実機转场 <2s + 卡牌动画余量）
    PANEL_CLICK_DELAY = 1.6   # 面板/详情点开后渲染等待（実機校准）
    TRANSITION_TIMEOUT_S = 60 # 转场窗口 60s（Q13 起步值，実機 2s 后续收紧）
    NO_PROGRESS_LIMIT = 3     # F4 守卫：同回合连续无进展步数上限
    UNVERIFIED_LIMIT = 2      # exec_verified 守卫：连续出牌未生效上限，触发 SKIP 兜底
    ROUND_DEADLINE_S = 1500    # 出牌全局上限 25 分钟(9/12 回合正常 <20 分钟,2026-08-22 收紧)
    EVIDENCE_RETRY = 2        # 手牌读空重试次数（Q12 禁盲点）
    ROUND_EXIT_ANCHORS = ("ラウンド1結果", "ラウンド2結果", "敗退", "インターバル", "優勝条件")

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        if preset.round1_mode != "play":
            return self._stop_unsupported(context, "round1_play", "round1_mode_not_play")

        total_turns, exam_round, round_tag = self._round_config(argv)
        screen_state = f"{round_tag}_play"
        deadline = time.time() + self.ROUND_DEADLINE_S
        _ProduceHIFActionBase._reset_round1_state()
        played_history: List[str] = []
        no_progress = 0
        unverified_plays = 0
        logger.success(f"HIF {round_tag} 出牌开始（play 模式，{total_turns} 回合）")
        # 対局页确认（実機 2026-08-22 轮0：Round 已结束重入时画面在結果页，
        # 开局槽探测会误点結果页元素——残りターン锚 miss 即跳过全部开局探测）
        opening_image = self._get_screenshot(context)
        on_battle_page = self._read_turn_left(context, opening_image) is not None
        opening_panel = None
        p_drink_slots = []
        p_items = None
        deck_state = None
        if on_battle_page:
            # 开局全量一次（实证修正 2026-08-21 probe4 round5：首行详情面板=组合视图无再演行,
            # 完整清单面板仅溢出态省略号入口——非溢出时状态带本就全量可见,走枚举即可）
            rows0 = self._enumerate_buff_rows(context, opening_image)
            if any(r.get("overflow") for r in rows0):
                opening_panel = self._read_state_panel(context, self.PANEL_ENTRY_ELLIPSIS)
                if opening_panel:
                    logger.info(f"{round_tag} 开局溢出完整面板: {len(opening_panel['items'])} 条, "
                                f"集中={opening_panel['focus']}, 再演剩余={opening_panel['reprise_left']}")
                else:
                    logger.warning(f"{round_tag} 溢出面板读取失败,降级状态带可见行")
            else:
                logger.info(f"{round_tag} 开局非溢出,状态带枚举 {sum(1 for r in rows0 if r.get('words'))} 行全量可见")
            # P 饮料槽探测（R1-Q1/R2：槽位前缀固定，点开弹窗实锤，缓存 session；
            # 段重入带缓存时跳过——不再反复点瓶位弹「尝试喝饮料」观感）
            cached = _ProduceHIFActionBase._read_round1_state().get("p_drink_slots") or []
            if cached:
                p_drink_slots = cached
                logger.info(f"{round_tag} P饮料槽用缓存({self._available_drinks_from_slots(cached)})")
            else:
                p_drink_slots = self._probe_p_drink_slots(context)
                logger.info(f"{round_tag} P饮料槽探测={self._available_drinks_from_slots(p_drink_slots)}")
            # 対局资源全景开局读取（五轮验证 A/B）：P item 详情 + 牌堆全状态，缓存 session 供 _build_state。
            # 五轮复盘 Q3（2026-08-22）：入口坐标未校准致 106 次 miss 降级纯耗时，且
            # 策略不消费此二字段（审计缺口 4）——默认关，実機取证校准后经 GUI/override
            # 注入 probe_opening_resources 打开
            if preset.probe_opening_resources:
                p_items = self._read_p_item_details(context)
                logger.info(f"{round_tag} P道具详情读取={len(p_items) if p_items is not None else 'FAIL'}件")
                deck_state = self._read_deck_state(context)
                logger.info(f"{round_tag} 牌堆状态读取={ {k: len(v) for k, v in (deck_state or {}).items()} if deck_state else 'FAIL' }")
            else:
                logger.info(f"{round_tag} 开局资源探测关闭(默认,p_items/牌堆坐标未校准)")
        else:
            logger.warning(f"{round_tag} 开局非対局页(重入/已结束?),跳过开局探测直接出口判定")

        while True:
            if time.time() > deadline:
                # ROUND_DEADLINE_S 此前定义未检查（実機轮6 发现 #46）——
                # continue 类自愈分支增多后必须有全局上限防慢循环
                return self._stop_unsupported(context, screen_state, "round_deadline_exceeded")
            image = self._get_screenshot(context)
            turn_left = self._read_turn_left(context, image)
            if turn_left is None:
                # 动画/转场窗口重试一次（実機首跑：面板关闭动画内截图致读空误停）；
                # 弹窗残留也挡仪表（実機 2026-08-22 轮1 R1:槽探测 P饮料弹窗残留
                # turn None stop）——先自愈浮层再重读
                time.sleep(self.ACTION_DELAY)
                if self._dissolve_blocking_overlays(context):
                    time.sleep(self.ACTION_DELAY)
                image = self._get_screenshot(context)
                turn_left = self._read_turn_left(context, image)
            if turn_left is None:
                # 残りターン消失≠异常：Round 结束转結果页时本来就没有（実機 2026-08-22
                # 轮0：turn9 出完牌转場被误判 turn_counter_unreadable）。出口锚 20s
                # （実測转場 <5s，60s 白等收紧）；无锚再区分「段边界演出动画」与
                # 「真异常」（実機轮6 #45：段重入落在演出半渲染窗口 stop ×4，
                # 段重启 20-30s 自愈——就地等动画静止重读，省段重启开销）
                if self._wait_round_exit(context):
                    logger.success(f"HIF {round_tag} 出牌完成（出口页已到，共出 {len(played_history)} 张）")
                    return True
                if self._wait_turn_reframe(context):
                    logger.info(f"{round_tag} turn 读空但画面在动(演出/转场)，静止后重读")
                    continue
                return self._stop_unsupported(context, screen_state, "turn_counter_unreadable")
            if turn_left == 0:
                logger.success(f"HIF {round_tag} 出牌完成：共出 {len(played_history)} 张")
                return True

            hand = ExamStateReader.from_context(context).read_hand()
            hand = self._filter_gray_hand(context, hand)
            if not hand.card_names:
                # 面板/弹窗残留自愈（実機 2026-08-22 轮0 两次 stop 根因：出牌循环
                # 打开的 buff 面板/P item 弹窗关闭失败后遮挡手牌，YOLO 恒 miss）
                if self._dissolve_blocking_overlays(context):
                    time.sleep(self.ACTION_DELAY)
                    hand = ExamStateReader.from_context(context).read_hand()
            if not hand.card_names:
                # 空手=回合转场/抽卡动画中，长窗口等 turn 变化（与出牌后短等待区分）
                if not self._wait_transition(context, turn_left, timeout_s=30):
                    # 兜位(vision 診断 2026-08-22 轮4):単卡居中布局 YOLO 恒 miss 画面却
                    # 是正常待出牌态——SKIP 锚在则强制 SKIP 推进回合(弃当回合保主线)
                    skip_img = self._get_screenshot(context)
                    if self._find_text_option(context, skip_img, ("SKIP",), [600, 740, 110, 80]):
                        logger.warning(f"{round_tag} 空手但待出牌态(SKIP 在),强制 SKIP 推进(単卡 YOLO miss)")
                        if self._click_skip(context):
                            continue
                    no_progress += 1
                    if no_progress >= self.NO_PROGRESS_LIMIT:
                        return self._stop_unsupported(context, screen_state, "evidence_empty_hand")
                    continue
                continue
            no_progress = 0

            state = self._build_state(context, image, turn_left, hand, exam_round, total_turns)
            evidence = self._collect_evidence(context, image, turn_left)
            evidence["hand"] = list(hand.card_names)
            # 指纹变化触发面板重读（grill R1-Q3：新 buff 出现指纹必变）
            fp = evidence.get("buff_fingerprint") or ""
            if fp and fp != _ProduceHIFActionBase._read_round1_state().get("last_buff_fingerprint"):
                rows_now = self._enumerate_buff_rows(context, image)
                if any(r.get("overflow") for r in rows_now):
                    refreshed = self._read_state_panel(context, self.PANEL_ENTRY_ELLIPSIS)
                    if refreshed:
                        evidence["panel_refreshed"] = True
                _ProduceHIFActionBase._write_round1_state({"last_buff_fingerprint": fp})
            action = GarakutaRinamiStrategy(ProfilePayload.default()).decide(state)
            logger.info(
                f"{round_tag} turn={state.turn} 残り{turn_left} gc={state.good_condition_turns} "
                f"focus={state.focus} stamina={state.stamina} flow={state.current_flow} "
                f"score={evidence.get('total_score')} → {action.kind.value}"
                f"{('/' + action.target_card) if action.target_card else ''}"
            )

            if action.kind is ActionKind.USE_P_DRINK:
                # Q9+A5:瓶位语义未定案,拦截只记录,降级 SKIP 回体(禁猜测性点击)
                logger.warning(f"{round_tag} USE_P_DRINK 拦截(记录不点): {action.target_card}")
                self._archive_round1_play(image, self.build_round1_play_record(
                    state, action, played_history[-1:], dry_run=True,
                    evidence={**evidence, "intercepted": "p_drink_semantics_undefined"},
                ), screen_state)
                action = CardAction(ActionKind.SKIP, None, f"[P饮料拦截降级] {action.reason}")

            ok, played_card = self._execute_action(context, action, hand)
            if not ok:
                no_progress += 1
                if no_progress >= self.NO_PROGRESS_LIMIT:
                    return self._stop_unsupported(context, screen_state, "action_execute_failed")
                continue

            if played_card:
                played_history.append(played_card)
                self._record_session_progress(played_card)

            # exec_verified 闭环（bug#44，実機 2026-08-22 轮5 turn7 假成功 17 条卡
            # 25 分钟教训）：_execute_action 的 SELECT 验证通过≠牌生效——出牌后
            # turn/总分/手牌数任一变化才判生效；连续 ≥2 次未生效强制 SKIP 推进回合，
            # 防同回合同卡假成功死循环（no_progress 守卫管不到 ok=True 的假成功）。
            verified = self._verify_play_effect(
                context, turn_left, evidence.get("total_score"), len(hand.card_names),
            )
            if not verified:
                unverified_plays += 1
                logger.warning(
                    f"{round_tag} 出牌未生效确认（连续 {unverified_plays}/{self.UNVERIFIED_LIMIT}）"
                    f" action={action.kind.value} target={action.target_card}"
                )
                if unverified_plays >= self.UNVERIFIED_LIMIT:
                    logger.warning(f"{round_tag} 连续出牌未生效，SKIP 兜底推进回合（弃当回合保主线）")
                    self._click_skip(context)
                    unverified_plays = 0
            else:
                unverified_plays = 0

            self._archive_round1_play(image, self.build_round1_play_record(
                state, action, [played_card] if played_card else [],
                turn_score=evidence.get("total_score"), evidence=evidence,
                exec_verified=verified,
            ), screen_state)

            # 等回合转场（残りターン变化）；未变化则继续同回合下一步
            self._wait_transition(context, turn_left)

    @staticmethod
    def _round_config(argv: CustomAction.RunArg) -> tuple[int, ExamRound, str]:
        """参数化回合配置（R1/R2 共用大包）：custom_action_param 的
        total_turns(9/12)/round("r1"/"r2")/round_tag(落盘 screen 前缀)。"""
        try:
            params = json.loads(argv.custom_action_param) if argv.custom_action_param else {}
        except ValueError:
            params = {}
        if not isinstance(params, dict):
            params = {}
        total = params.get("total_turns") or 9
        exam_round = ExamRound.HONSEN_R2 if params.get("round") == "r2" else ExamRound.HONSEN_R1
        tag = params.get("round_tag") or ("round2" if exam_round is ExamRound.HONSEN_R2 else "round1")
        return int(total), exam_round, tag

    # ------------------------------------------------------------------
    # 画面读取（Q6 画面优先；读不到回退 session/默认值并告警）
    # ------------------------------------------------------------------

    def _wait_round_exit(self, context: Context) -> bool:
        """等待 Round 出口页（結果/敗退/Interval/優勝条件），20s 轮询
        （実測转場 <5s,60s 白等——2026-08-22 收紧）。
        出口锚宽扫顶部区——区分「转場窗口」与「真异常」（画面冻结/未知页）。"""
        deadline = time.time() + 20
        while time.time() < deadline:
            image = self._get_screenshot(context)
            hit = self._find_text_option(
                context, image, self.ROUND_EXIT_ANCHORS,
                [0, 0, 720, 300],
            )
            if hit:
                return True
            time.sleep(2.0)
        return False

    def _wait_turn_reframe(self, context: Context, timeout_s: float = 90.0) -> bool:
        """turn 读不到且出口锚无果时，区分「演出/转场动画中」与「真异常」
        （実機 2026-08-22 轮6 #45：turn_counter_unreadable stop ×4 均为段
        重入落在演出半渲染窗口，段重启 20-30s 后动画播完自愈）。指纹在变
        =动画中：等到静止再让调用方重读 turn；出口锚出现=Round 已结束直接
        True；超时且从未变化=画面冻结/未知页，False 交 stop。"""
        deadline = time.time() + timeout_s
        seen_change = False
        prev = self._safe_fingerprint(context)
        while time.time() < deadline:
            time.sleep(3.0)
            image = self._get_screenshot(context)
            if self._find_text_option(context, image, self.ROUND_EXIT_ANCHORS, [0, 0, 720, 300]):
                return True
            cur = self._fingerprint(image)
            if cur and prev:
                if cur != prev:
                    seen_change = True
                elif seen_change:
                    return True  # 动画播完已静止，重读 turn
            prev = cur
        return seen_change

    def _read_turn_left(self, context: Context, image) -> Optional[int]:
        """残りターン读取。実機 2026-08-22 轮2 R2 后期:buff 带行(「37ターン」等)
        挤入 ROI 混读出 M21/37 类伪值——加回合数上限校验,越界视为未读到
        (走 dissolve/出口判定路径而非错误出牌)。"""
        detail = self._run_ocr(
            context, image, "HIFRound1TurnLeft", [".*"], self.ROI_TURN,
        )
        text = detail.best_result.text if (detail and detail.hit) else ""
        if not self._valid_turn_text(text):
            # 圆环指示器内数字(実機 2026-08-22 轮2 R2 残り4:白字深蓝圆底直读不出)
            # →crop 圆圈区放大 3 倍重读(同 buff 数字带 crop-zoom 模式)
            text = self._read_turn_zoomed(context, image)
        if not self._valid_turn_text(text):
            return None
        digits = re.sub(r"\D", "", text)
        value = int(digits)
        return value if 0 <= value <= max(self.TOTAL_TURNS, 13) else None

    def _valid_turn_text(self, text: str) -> bool:
        digits = re.sub(r"\D", "", text or "")
        return bool(digits) and 0 <= int(digits) <= max(self.TOTAL_TURNS, 13)

    def _read_turn_zoomed(self, context: Context, image) -> str:
        fx, fy, fw, fh = 15, 40, 100, 80  # 残りターン圆环指示器区
        crop = image[fy:fy + fh, fx:fx + fw]
        if crop.size == 0:
            return ""
        pil = Image.fromarray(crop[..., ::-1]).resize((fw * 3, fh * 3), Image.LANCZOS)
        zoomed = np.array(pil)[..., ::-1]
        detail = self._run_ocr(
            context, zoomed, "HIFRound1TurnLeftZoom", [".*"],
            [0, 0, zoomed.shape[1], zoomed.shape[0]],
        )
        return detail.best_result.text if (detail and detail.hit) else ""  # 覆盖 R2 12T

    def _read_int_ocr(self, context: Context, image, name: str, roi: list[int]) -> Optional[int]:
        detail = self._run_ocr(context, image, name, [".*"], roi)
        if not (detail and detail.hit):
            return None
        digits = re.sub(r"\D", "", detail.best_result.text)
        return int(digits) if digits else None

    def _read_flow(self, context: Context, image) -> str:
        """分带双 OCR（grill 定案 2026-08-21 R1-Q3）：名带/数带各一次紧裁 OCR，
        名带命中日文映射优先；两带都无名 → "Vi" 缺省（実機曾整带 OCR 丢名致
        ダンス误判 Vi，probe 实测）。"""
        # 名带是小字（ダンス ~59x24px 実測原尺寸 OCR 读不出），crop 放大 3 倍再读
        # ROI 惯例 [x,y,w,h]（実機首验 y 切片反向致空图,勿当 x1y1x2y2 用）
        fx, fy, fw, fh = self.ROI_FLOW_NAME
        crop = image[fy:fy + fh, fx:fx + fw]
        if crop.size:
            pil = Image.fromarray(crop[..., ::-1]).resize((fw * 3, fh * 3), Image.LANCZOS)
            zoomed = np.array(pil)[..., ::-1]
            for jp, flow in (("ビジュアル", "Vi"), ("ボーカル", "Vo"), ("ダンス", "Da")):
                detail = self._run_ocr(
                    context, zoomed, "HIFRound1FlowName", [f".*{jp}.*"],
                    [0, 0, zoomed.shape[1], zoomed.shape[0]],
                )
                if detail and detail.hit:
                    return flow
        num_detail = self._run_ocr(context, image, "HIFRound1FlowNum", [".*"], self.ROI_FLOW_NUM)
        if num_detail and num_detail.hit:
            raw = num_detail.best_result.text
            for flow in ("Vo", "Da", "Vi"):
                if flow in raw:
                    return flow
        return "Vi"

    def _read_buff_turns(self, context: Context, image, template: str) -> Optional[int]:
        """图标模板在状态带定行 → 同行右侧数字 OCR（行位置动态重排，坐标定行不可靠）。

        threshold 0.85：好調/絶好調图标同族相似（离线交叉实测 2026-08-21：自匹配 1.0、
        互配 0.704/0.729），0.85 以上才能区分两行；集中模板同带亦适用。
        数字带（好調 9ターン/絶好調 3ターン/集中 8 均离线实测 1.0）位于图标右下，
        原始尺寸仅 ~14×16px 直接 OCR 读不出，须 crop 放大 3 倍再读。
        """
        detail = self._run_template(
            context, image, "HIFRound1BuffIcon", template, self.ROI_BUFF_BAND, threshold=0.85,
        )
        if not (detail and detail.hit):
            return None
        box = detail.best_result.box
        # 数字带相对图标 box 的偏移（実機 turn03_pre 校准）：右侧 x+box.w-6 起，
        # 纵向 icon.y-13 ~ icon.y+64（数字在图标右下方，比图标中心低 ~12px）
        x1 = box[0] + box[2] - 6
        y1 = max(0, box[1] - 13)
        y2 = min(1280, box[1] + 64)
        cropped = image[y1:y2, x1:140]
        if cropped.size == 0:
            return None
        pil = Image.fromarray(cropped[..., ::-1])  # maafw 截图为 BGR
        pil = pil.resize((pil.width * 3, pil.height * 3), Image.LANCZOS)
        zoomed = np.array(pil)[..., ::-1]
        detail_num = self._run_ocr(
            context, zoomed, "HIFRound1BuffNum", [".*"], [0, 0, zoomed.shape[1], zoomed.shape[0]],
        )
        if not (detail_num and detail_num.hit):
            return None
        digits = re.sub(r"\D", "", detail_num.best_result.text)
        return int(digits) if digits else None

    def _read_reprise_used(self, context: Context, image) -> Optional[int]:
        """再演剩余 → 已用。実機 2026-08-21 复盘：右上「N回」实为 P item 触发剩余
        （云朵详情=憧れ続けた輝き类效果链实锤），旧源错误；真身疑状态带
        「ターン内1回」行（お姉さん面板「4回まで・ターン内1回まで」同构文案）。
        grill R1-Q5 裁决：双读落盘，决策暂用旧源+告警，出牌 diff 实测后切换。"""
        left = self._read_int_ocr(context, image, "HIFRound1Reprise", self.ROI_REPRISE)
        if left is None or left < 0 or left > 4:
            return None
        return 4 - left

    def _read_reprise_new_source(self, context: Context, image) -> Optional[int]:
        """新源（待実機 diff 定案后切换）：状态带 OCR 锚「ターン内1回」→ 同行数字 → 已用 = 4-N。"""
        # 锚放宽：実測该行 OCR 常残读（「ターン内1回」→「一ン内」），全词锚必 miss；
        # 行数字（N回）在锚左侧同行（実測 锚[81,635] 数字[58,602]），取行带内数字
        detail = self._run_ocr(
            context, image, "HIFRound1RepriseRowAnchor", [".*ン内.*"], [14, 580, 130, 90],
        )
        if not (detail and detail.hit):
            return None
        row = self._run_ocr(context, image, "HIFRound1RepriseRowNum", [".*"], [40, 585, 90, 60])
        if not (row and row.hit):
            return None
        digits = re.sub(r"\D", "", row.best_result.text)
        n = int(digits) if digits else None
        if n is None or n < 0 or n > 4:
            return None
        return 4 - n

    def _read_p_item_progress(self, context: Context, image) -> Optional[int]:
        """右上 P item 触发剩余（云朵旁数字，原 reprise ROI 改标；仅落盘不进决策）。"""
        return self._read_int_ocr(context, image, "HIFRound1PItemProgress", self.ROI_REPRISE)

    @staticmethod
    def _max_int_from_ocr(detail) -> Optional[int]:
        """OCR 结果取最大整数值（総分 ROI 含邻位小数字，総分单调增且远大于邻数）。"""
        if not (detail and detail.hit):
            return None
        values = []
        for item in (detail.all_results or []):
            digits = re.sub(r"\D", "", item.text)
            if digits:
                values.append(int(digits))
        return max(values) if values else None

    def _read_total_score(self, context: Context, image) -> Optional[int]:
        """右上総分 → turn_score 落盘来源。実測 ROI 内含邻位小数字（70/0），
        best_result 会选错框——取 all_results 最大数值（総分单调增且远大于邻数）。
        直读 miss（五轮复盘 10-12% 读空，2026-08-22 Q4）→ ROI crop 放大 3 倍重读
        （_read_turn_zoomed 同模式）。"""
        detail = self._run_ocr(context, image, "HIFRound1TotalScore", [".*"], self.ROI_TOTAL_SCORE)
        value = self._max_int_from_ocr(detail)
        if value is not None:
            return value
        fx, fy, fw, fh = self.ROI_TOTAL_SCORE
        crop = image[fy:fy + fh, fx:fx + fw]
        if crop.size == 0:
            return None
        pil = Image.fromarray(crop[..., ::-1]).resize((fw * 3, fh * 3), Image.LANCZOS)
        zoomed = np.array(pil)[..., ::-1]
        zoom_detail = self._run_ocr(
            context, zoomed, "HIFRound1TotalScoreZoom", [".*"],
            [0, 0, zoomed.shape[1], zoomed.shape[0]],
        )
        return self._max_int_from_ocr(zoom_detail)


    def _build_state(self, context: Context, image, turn_left: int, hand,
                     exam_round: ExamRound = ExamRound.HONSEN_R1, total_turns: int = 9) -> ExamState:
        session = _ProduceHIFActionBase._read_round1_state()
        good = self._read_buff_turns(context, image, self.TPL_GOOD)
        focus = self._read_buff_turns(context, image, self.TPL_CONC)
        if focus is None:
            # 集中双保险（grill R1-Q4）：状态带模板 MISS 时用开局面板缓存+告警
            focus = int(session.get("focus_cached") or 0) or None
            if focus is not None:
                logger.info(f"集中模板 MISS，用面板缓存={focus}")
        # reprise 源（实证修正）：溢出面「(再演)」权威缓存优先；非溢出=状态带「ーン内」行
        # 新源；旧右上源（P item 误标）仅 debug 落盘
        pool_left = session.get("reprise_pool_left")
        if pool_left is not None:
            reprise_used = 4 - int(pool_left)
        else:
            new_src = self._read_reprise_new_source(context, image)
            reprise_used = new_src if new_src is not None else self._read_reprise_used(context, image)
        if good is None:
            logger.warning(f"好調行模板定行失败，session 兜底={session.get('good_condition_turns')}")
        if reprise_used is not None:
            # 双源告警（R1-Q5）：旧源右上 N 回实为 P item 剩余，实测 diff 定案前保留+告警
            logger.warning(f"reprise 旧源(右上,疑 P item 误标)={reprise_used}, 出牌 diff 后切换新源")
        # 対局资源全景（五轮验证接口）：开局读取缓存 session，决策从这里消费
        p_drink_slots = session.get("p_drink_slots") or []
        p_items = session.get("p_items") or []
        deck_state = session.get("deck_state") or {}
        return ExamState(
            round=exam_round,
            turn=total_turns - turn_left + 1,
            total_turns=total_turns,
            current_flow=self._read_flow(context, image),
            good_condition_turns=good if good is not None else int(session.get("good_condition_turns") or 0),
            focus=focus if focus is not None else 0,
            stamina=self._read_int_ocr(context, image, "HIFRound1Stamina", self.ROI_STAMINA) or 0,
            hand=hand,
            reprise_count=reprise_used if reprise_used is not None else int(session.get("reprise_count") or 0),
            cards_played=int(session.get("cards_played") or 0),
            deck_size=max(0, 22 - int(session.get("cards_played") or 0)),  # A4:画面不可读,session 自维护近似
            oneesan_used=bool(session.get("oneesan_used", False)),
            natural_finisher_used=bool(session.get("natural_finisher_used", False)),
            available_p_drinks=self._available_drinks_from_slots(p_drink_slots),
            p_items=p_items,
            p_drinks=p_drink_slots,
            deck=deck_state,
        )

    def _collect_evidence(self, context: Context, image, turn_left: int) -> Dict[str, Any]:
        """落盘扩展（grill R1-Q6）：evidence 增 p_item_progress/total_score/flow_raw/
        reprise 双源，供 diff 定案与 roundsim 校准。"""
        flow_raw = self._run_ocr(context, image, "HIFRound1FlowNum", [".*"], self.ROI_FLOW_NUM)
        flow_text = flow_raw.best_result.text if (flow_raw and flow_raw.hit) else None
        p_items = self._enumerate_p_items(context, image)
        return {
            "turn_left": turn_left,
            "p_item_progress": self._read_p_item_progress(context, image),
            "p_items": p_items,
            "total_score": self._read_total_score(context, image),
            "flow_raw": flow_text,
            "reprise_legacy": self._read_reprise_used(context, image),
            "reprise_new": self._read_reprise_new_source(context, image),
            "buff_rows": self._enumerate_buff_rows(context, image),
            "buff_fingerprint": self._buff_fingerprint(context, image),
            "p_drink_slots": _ProduceHIFActionBase._read_round1_state().get("p_drink_slots") or [],
        }

    def _record_session_progress(self, played_card: str) -> None:
        """出牌后更新 session round1 跨回合字段（Q6：session 只存画面外字段）。"""
        base = normalize_card_name(played_card).rstrip("+")
        session = _ProduceHIFActionBase._read_round1_state()
        patch: Dict[str, Any] = {"cards_played": int(session.get("cards_played") or 0) + 1}
        if base == "お姉さんの感覚":
            patch["oneesan_used"] = True
        elif base == "自然体の魅力":
            patch["natural_finisher_used"] = True
        _ProduceHIFActionBase._write_round1_state(patch)

    # ------------------------------------------------------------------
    # 执行层（Q12：原坐标重试 ≤2；SELECT 跟随选中卡漂移）
    # ------------------------------------------------------------------

    def _filter_gray_hand(self, context: Context, hand):
        """hand 层灰卡过滤(2026-08-22 规划:策略输入端只见可用卡,目标天然可出;
        执行层无需再偏离策略退首张)。全灰/判定异常时保守不过滤。"""
        if not hand.card_names:
            return hand
        try:
            image = self._get_screenshot(context)
            detections = ExamStateReader.from_context(context).ocr.run_yolo_cards()
            usable = {normalize_card_name(d.card_name).rstrip("+") for d in detections
                      if d.card_name and not self._is_gray_card(image, tuple(d.box))}
            if not usable:
                return hand
            filtered = tuple(n for n in hand.card_names
                             if normalize_card_name(n).rstrip("+") in usable)
            if len(filtered) < len(hand.card_names):
                logger.info(f"hand 灰卡过滤: {list(hand.card_names)} -> {list(filtered)}")
                return dataclasses.replace(hand, card_names=filtered)
        except Exception as err:
            logger.debug(f"hand 灰卡过滤异常(不过滤): {err}")
        return hand

    GRAY_CARD_SAT_THRESHOLD = 40  # 卡框带 HSV 饱和度均值阈值(灰卡<40,用户 UI 约束
    # 2026-08-22:消耗超出当前状态(体力/集中不足)时卡牌变灰——灰卡点击不生效,须跳过)

    @staticmethod
    def _band_saturation(arr: "np.ndarray") -> float:
        """RGB 数组平均饱和度(0-255,HSL 的 S 近似=(max-min)/max)。"""
        if arr.size == 0:
            return 255.0
        a = np.asarray(arr, dtype=np.float32)
        mx = a.max(axis=2) + 1e-6
        mn = a.min(axis=2)
        return float(((mx - mn) / mx).mean() * 255)

    @classmethod
    def _is_gray_card(cls, image, box: tuple[int, int, int, int]) -> bool:
        """灰卡判定:卡框**四边环带**(各 1/12)饱和度均值(消耗不足时卡整体去饱和,
        用户 UI 约束;四边环避开卡面插图区,比单上边带抗内容干扰——2026-08-22 规划)。
        首次実機触发时日志带饱和度值供阈值校准。"""
        x, y, w, h = (int(v) for v in box[:4])
        t = max(3, h // 12)
        s = max(3, w // 12)
        H, W = image.shape[:2]
        x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
        if x1 - x0 < s * 2 or y1 - y0 < t * 2:
            return False
        arr = np.asarray(image[y0:y1, x0:x1, ::-1])  # BGR→RGB
        ih, iw = arr.shape[:2]
        bands = [
            arr[:t, :, :],           # 上
            arr[ih - t:, :, :],       # 下
            arr[:, :s, :],           # 左
            arr[:, iw - s:, :],       # 右
        ]
        sat = float(np.mean([cls._band_saturation(b) for b in bands]))
        is_gray = sat < cls.GRAY_CARD_SAT_THRESHOLD
        if is_gray:
            # 判灰每次 info 带 sat 值(五轮 0 触发=低频不刷屏)——遗留#5 阈值
            # 実機校准数据源(2026-08-22 五轮复盘 Q5)
            logger.info(
                f"灰卡判定触发 sat={sat:.0f}(<{cls.GRAY_CARD_SAT_THRESHOLD}) "
                f"box={tuple(int(v) for v in box[:4])}"
            )
        else:
            logger.debug(f"非灰卡 sat={sat:.0f} box={box[:4]}")
        return is_gray

    def _execute_action(self, context: Context, action: CardAction, hand) -> tuple[bool, Optional[str]]:
        if action.kind is ActionKind.SKIP:
            return self._click_skip(context), None

        target = (normalize_card_name(action.target_card).rstrip("+")
                  if action.target_card else None)
        reader = ExamStateReader.from_context(context)
        detections = reader.ocr.run_yolo_cards()
        image = self._get_screenshot(context)
        gray_names: list[str] = []
        usable = []
        for d in detections:
            name = normalize_card_name(d.card_name).rstrip("+") if d.card_name else ""
            if self._is_gray_card(image, tuple(d.box)):
                if name:
                    gray_names.append(name)
                continue
            usable.append((d, name))
        if gray_names:
            logger.info(f"Round 灰卡过滤(消耗不足变灰,不可出): {gray_names}")
        chosen = None
        for d, name in usable:
            if target and name == target:
                chosen = d
                break
        if chosen is None and not target:
            chosen = next((d for d, name in usable if name), None)
        if chosen is None and target:
            # 目标卡灰/不在——退可用首张(策略目标不可达时不空转,保推进)
            if usable:
                chosen = usable[0][0]
                logger.warning(f"Round 目标卡不可用(灰/未检出) target={target},退可用首张")
        if chosen is None:
            logger.warning(f"Round1 目标卡未命中 target={target}，hand={list(hand.card_names)}")
            return False, None

        box = list(chosen.box)
        for attempt in range(3):
            if not self._click_box_center(context, box, double=False):
                return False, None
            time.sleep(1.6)
            if self._click_select(context):
                time.sleep(self.SETTLE_DELAY)
                return True, chosen.card_name
            logger.info(f"Round1 SELECT 未出现/未生效，重试 {attempt + 1}/3")
        return False, None

    def _verify_play_effect(
        self, context: Context, prev_turn_left: int,
        prev_score: Optional[int], prev_hand_count: int,
    ) -> bool:
        """出牌执行确认（bug#44）：turn/总分/手牌数任一变化才判生效。

        SELECT 按钮点击成功≠牌打出（実機轮5 turn7：17 次假成功卡 25 分钟，
        no_progress 守卫因 ok=True 永不触发）。同回合连续出牌 turn 不变是正常的，
        三分量任一变化即生效；全部不变=假成功。动画期读空（turn None/手牌空/
        score None）不可信，跳过该分量继续轮询，不误判。窗口 6s 覆盖结算
        动画（実機转场 <2s）。"""
        deadline = time.time() + 6
        while time.time() < deadline:
            time.sleep(1.5)
            image = self._get_screenshot(context)
            turn_left = self._read_turn_left(context, image)
            if turn_left is not None and turn_left != prev_turn_left:
                return True
            names = ExamStateReader.from_context(context).read_hand().card_names
            if names and len(names) != prev_hand_count:
                return True
            score = self._read_total_score(context, image)
            if score is not None and prev_score is not None and score != prev_score:
                return True
        return False

    def _click_select(self, context: Context) -> bool:
        for attempt in range(2):
            image = self._get_screenshot(context)
            detail = self._run_ocr(
                context, image, "HIFRound1Select", [".*SELECT.*"], self.ROI_SELECT,
            )
            if detail and detail.hit:
                if self._click_box_center(context, detail.best_result.box, double=False):
                    return True
        return False

    def _click_skip(self, context: Context) -> bool:
        for attempt in range(3):
            self._tap(context, *self.CLICK_SKIP)
            time.sleep(2.0)
            image = self._get_screenshot(context)
            # SKIP 后转场（残りターン变化）或手牌空提示消失即视为生效
            if not self._find_text_option(context, image, ("SKIP",), [600, 760, 110, 70]):
                return True
        return self._wait_transition_click(context)

    def _wait_transition_click(self, context: Context) -> bool:
        """SKIP 兜底：等待画面脱离当前可操作态（実機 SKIP 后 <2s 转场）。"""
        deadline = time.time() + 10
        while time.time() < deadline:
            image = self._get_screenshot(context)
            if not self._find_text_option(context, image, ("SKIP",), [600, 760, 110, 70]):
                return True
            time.sleep(1.0)
        return False

    def _wait_transition(self, context: Context, prev_turn_left: int, timeout_s: int = 8) -> bool:
        """等待回合转场（残りターン变化）：短窗口轮询（実機 2026-08-22 轮0 复盘：
        同回合连续出牌时 turn 不变，60s 死等让 9 回合拖到 25 分钟）。超时返回 False
        交回主循环重读画面（转场动画期容错由主循环 turn None 重试承担），
        转场真正超过 8s 的大动画由 no_progress 守卫兜底而非此处死等。"""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            time.sleep(1.5)
            image = self._get_screenshot(context)
            turn_left = self._read_turn_left(context, image)
            if turn_left is not None and turn_left != prev_turn_left:
                return True
        return False

    # ------------------------------------------------------------------
    # 完整状态识别：开局全量层 + 触发层（grill 三层设计，2026-08-21 计划批准）
    # 全部为纯读取动作（不点使う/不做决策），probe3 可独立実機验证
    # ------------------------------------------------------------------

    PDRINK_SLOTS = ((60, 1215), (150, 1215), (240, 1215), (330, 1215))
    PDRINK_POPUP_ANCHOR_ROI = [40, 700, 500, 80]   # 弹窗标题「Pドリンク詳細」(y722 実測)
    PDRINK_NAME_ROI = [40, 780, 400, 80]           # 弹窗瓶名带（初星黒酢 [187,805] 実測）
    PDRINK_CANCEL_SCAN_ROI = [0, 1050, 400, 130]   # キャンセル按钮扫描带（[96,1124] 実測）
    ROI_BUFF_ENUM = [14, 237, 130, 420]            # buff 带全量（枚举+指纹）
    ROI_PITEM_COLUMN = [600, 230, 120, 150]        # P item 纵列（云朵/票券 実測 x620-720,y240-340）

    def _popup_is_pdrink(self, context: Context, image) -> bool:
        detail = self._run_ocr(context, image, "HIFPDrinkPopupAnchor", [".*ドリンク詳細.*"], self.PDRINK_POPUP_ANCHOR_ROI)
        return bool(detail and detail.hit)

    def _close_pdrink_popup(self, context: Context) -> bool:
        """OCR 锁定キャンセル点击并验证关闭（実機教训：固定坐标+不验证=弹窗残留污染后续读取）。"""
        for _ in range(3):
            image = self._get_screenshot(context)
            cancel = self._run_ocr(context, image, "HIFPDrinkCancel", [".*キャンセル.*"], self.PDRINK_CANCEL_SCAN_ROI)
            if cancel and cancel.hit:
                self._click_box_center(context, cancel.best_result.box, double=False)
                time.sleep(1.2)
            if not self._popup_is_pdrink(context, self._get_screenshot(context)):
                return True
        return False

    def _verify_p_drink(self, context: Context, slot_xy: tuple[int, int]) -> Optional[str]:
        """用药复核读取（grill R2-Q2 前半，纯读取不使う）：点槽→弹窗验证→读名→关→验证关。

        弹窗渲染慢时锚会 miss（実機 2026-08-22 轮0：槽2 ビタミンドリンク 弹窗
        渲染慢被误判 empty 且未关，残留弹窗遮挡手牌识别致 evidence_empty_hand），
        验证带一次重试；判 empty 前兜底关一次弹窗防残留。"""
        self._click_box_center(context, [slot_xy[0] - 20, slot_xy[1] - 20, 40, 40], double=False)
        time.sleep(self.PANEL_CLICK_DELAY)
        image = self._get_screenshot(context)
        if not self._popup_is_pdrink(context, image):
            time.sleep(self.ACTION_DELAY)
            image = self._get_screenshot(context)
            if not self._popup_is_pdrink(context, image):
                # 未开弹窗也兜底关一次（防半开态残留污染后续读取）
                self._close_pdrink_popup(context)
                return None  # 空槽/槽不存在（同语义，grill R2 用户确认）
        name_detail = self._run_ocr(context, image, "HIFPDrinkName", [".*"], self.PDRINK_NAME_ROI)
        name = name_detail.best_result.text.strip() if (name_detail and name_detail.hit) else ""
        self._close_pdrink_popup(context)
        return name or None

    def _probe_p_drink_slots(self, context: Context) -> list[dict]:
        """开局槽探测（grill R1-Q1/R2 用户确认：槽位前缀固定，点开弹窗为实锤）。
        结果（名称经 match_drink_name 匹配库内属性后）缓存 session.p_drink_slots；
        空槽/槽不存在同记 empty（3-4 格随亲密度，grill 用户约束）。"""
        slots = []
        for i, xy in enumerate(self.PDRINK_SLOTS, 1):
            raw = self._verify_p_drink(context, xy)
            name, record = (None, None)
            if raw:
                name, record = match_drink_name(raw)
                if name is None:
                    logger.warning(f"Round P饮料槽{i} 名匹配失败 raw={raw!r}")
            slots.append({
                "slot": i,
                "xy": list(xy),
                "raw": raw,
                "name": name,
                "effects": (record or {}).get("effects"),
            })
            logger.info(f"Round P饮料槽{i}: raw={raw or '(empty)'} matched={name or '(unmatched)'}")
        _ProduceHIFActionBase._write_round1_state({"p_drink_slots": slots})
        return slots

    @classmethod
    def _available_drinks_from_slots(cls, slots: list[dict]) -> list[str]:
        """纯逻辑（可单测）：缓存槽表 → available_p_drinks 名单（去空+保持槽序；
        库内规范名优先，匹配失败的回退 OCR 原文——语义与実機瓶名一致可用）。"""
        names = []
        for s in slots:
            name = s.get("name") or s.get("raw")
            if name:
                names.append(name)
        return names

    def _buff_fingerprint(self, context: Context, image) -> str:
        """整带指纹（触发层）：数字+单位词序列 join，回合间 diff 用（grill R1-Q1 触发细读）。"""
        detail = self._run_ocr(context, image, "HIFBuffFingerprint", [".*"], self.ROI_BUFF_ENUM)
        if not (detail and detail.hit):
            return ""
        parts = sorted((i.text.strip() for i in (detail.all_results or []) if i.text.strip()))
        return "|".join(parts)

    def _enumerate_buff_rows(self, context: Context, image) -> list[dict]:
        """buff 带枚举（开局全量层）。行定位=数字词框 y 聚行（実測行距~63，数字框 y 聚类
        误差 ±15 内同行）+已知模板识别（好調✅/絶好調・集中待素材）；ColorMatch 菱形
        底方案为 probe3 验证后的升级路径，首版用 OCR 词行+模板组合（计划允许的降级）。
        未知行记录 y+数字词，懒定案另法（_lazy_identify_row）。"""
        detail = self._run_ocr(context, image, "HIFBuffEnum", [".*"], self.ROI_BUFF_ENUM)
        words = [dict(text=i.text.strip(), box=list(i.box)) for i in (detail.all_results or []) if i.text.strip()]
        rows = self._cluster_buff_words_to_rows(words)
        known = {}
        for label, tpl in (("好調", self.TPL_GOOD), ("絶好調", "autodev/hif_buff_excellent_condition.png"), ("集中", self.TPL_CONC)):
            d = self._run_template(context, image, "HIFBuffKnown", tpl, self.ROI_BUFF_ENUM, threshold=0.85)
            if d and d.hit:
                known[round(d.best_result.box[1])] = label
        for row in rows:
            row["known"] = next((label for y, label in known.items() if abs(y - row["y"]) < 30), None)
        rows = self._mark_buff_overflow(context, image, rows)
        return rows

    BUFF_CAPACITY = 8  # 状态带容量実測上限（用户报告:溢出时末行折叠省略号,2026-08-21）

    def _mark_buff_overflow(self, context: Context, image, rows: list[dict]) -> list[dict]:
        """溢出检测（双信号）:OCR 检出省略号词 或 行数≥容量上限。决策不受影响
        （好調/集中实证恒在顶部不被截）,溢出标记驱动面板滚动兜底读取完整清单。"""
        ellipsis = self._run_ocr(context, image, "HIFBuffEllipsis", [".*….*|.*･･.*"], self.ROI_BUFF_ENUM)
        overflow = bool(ellipsis and ellipsis.hit) or len(rows) >= self.BUFF_CAPACITY
        if overflow:
            rows.append({"y": -1, "words": ["OVERFLOW_MARKER"], "known": None, "overflow": True})
        return rows

    PANEL_ENTRY_FIRST_ROW = 262   # 非溢出入口=状态带首行（好調行,実測 y~262）
    PANEL_ENTRY_ELLIPSIS = 620    # 溢出入口=省略号行（実証 竖两点「:」 y~620±40）
    PANEL_CONTENT_ROI = [40, 50, 560, 680]  # 状态面板内容区（两种入口同容器）
    PANEL_SCROLL_STEP = (545, 640, 545, 340)  # 右缘滚动 ~300px（実証:中央起点落面板条目区被消费致滚动时灵时不灵,右缘稳定）
    PANEL_SCROLL_MAX = 8
    PANEL_BOTTOM_CONFIRM = 2  # 连续 N 次滚动无新增才判到底（防单次 OCR 全漏误判）

    def _read_state_panel(self, context: Context, entry_y: int) -> Optional[dict]:
        """统一面板法（grill 三轮共识 2026-08-21）：点开（首行 or 省略号位）→ 小步滚动
        到底 → 全量清单（整行去重+count）→ 提取集中/再演 → 关闭验证。失败降级 return None
        （退回状态带可见行+告警，不 stop——面板是感知增强非决策必需）。

        防漏读（用户 grill 滚动规范）：半屏滚动+重叠锚（相邻屏零重叠=跳屏→回滚重读）+
        连续 2 次无新增到底 + 底部物理信号（到底后两帧 OCR 全同）。
        防重读（语义不丢）：整行文本为键，同名同值 count 计数，同名不同值不误并。
        """
        opened = False
        for dy in (0, -40, 40):
            self._click_box_center(context, [7, entry_y + dy - 24, 48, 48], double=False)
            time.sleep(self.PANEL_CLICK_DELAY)
            image = self._get_screenshot(context)
            # 锚词+条数下限双验证（probe4 実測教训:半开态锚词可误中,首屏<8 条非真开）
            if self._panel_anchor_hit(context, image) and len(self._ocr_panel_items(context, image)) >= 8:
                opened = True
                break
        if not opened:
            logger.warning(f"Round1 面板未打开(entry_y={entry_y}),降级状态带可见行")
            return None

        items: dict[str, int] = {}
        no_new_streak = 0
        for _ in range(self.PANEL_SCROLL_MAX):
            cur = self._ocr_panel_items(context, image)
            self._merge_panel_items(items, cur)
            prev_set = set(cur)
            # 半屏滚动（重叠锚:新屏应与上屏有重叠词,零重叠=跳屏→回滚半屏重读）
            self._swipe(context, *self.PANEL_SCROLL_STEP, 400)
            time.sleep(1.3)
            image = self._get_screenshot(context)
            nxt = self._ocr_panel_items(context, image)
            new_items = [t for t in nxt if t not in items]
            if prev_set and nxt and not (set(nxt) & prev_set) and not new_items:
                # 跳屏且无新增——回滚重读一次
                self._swipe(context, self.PANEL_SCROLL_STEP[2], self.PANEL_SCROLL_STEP[3],
                            self.PANEL_SCROLL_STEP[0], self.PANEL_SCROLL_STEP[1], 400)
                time.sleep(1.3)
                image = self._get_screenshot(context)
                nxt = self._ocr_panel_items(context, image)
                new_items = [t for t in nxt if t not in items]
            self._merge_panel_items(items, nxt)
            if new_items:
                no_new_streak = 0
            else:
                no_new_streak += 1
                if no_new_streak >= self.PANEL_BOTTOM_CONFIRM:
                    # 底部物理信号:再滚一帧对比,全同确认到底
                    self._swipe(context, *self.PANEL_SCROLL_STEP, 400)
                    time.sleep(1.0)
                    probe = self._ocr_panel_items(context, self._get_screenshot(context))
                    if set(probe) <= set(items):
                        break
                    no_new_streak = 0

        record = {
            "items": [{"text": t, "count": c} for t, c in items.items()],
            "focus": self._extract_focus_from_items(items),
            "reprise_left": self._extract_reprise_from_items(items),
        }
        self._close_state_panel(context)
        # 缓存跨回合字段（reprise 权威源/集中兜底缓存）
        patch: Dict[str, Any] = {}
        if record["reprise_left"] is not None:
            patch["reprise_pool_left"] = record["reprise_left"]
        if record["focus"] is not None:
            patch["focus_cached"] = record["focus"]
        if patch:
            _ProduceHIFActionBase._write_round1_state(patch)
        return record

    def _panel_anchor_hit(self, context: Context, image) -> bool:
        """面板打开判定：内容区出现清单词（再演/絶好調——状態带没有的词;
        「ターン内」状態带同词不可用作锚,実機误报教训）。"""
        anchor = self._run_ocr(context, image, "HIFStatePanelAnchor",
                               [".*再演.*|.*絶好調.*"], self.PANEL_CONTENT_ROI)
        return bool(anchor and anchor.hit)

    def _ocr_panel_items(self, context: Context, image) -> list[str]:
        detail = self._run_ocr(context, image, "HIFStatePanelItems", [".*"], self.PANEL_CONTENT_ROI)
        raw = [i.text.strip() for i in (detail.all_results or []) if i.text.strip()]
        # 噪声过滤:<4 字符且非数字的残读丢弃（「č」「ć」类,実証出现过）
        return [t for t in raw if len(t) >= 4 or t.isdigit()]

    @staticmethod
    def _panel_item_key(text: str) -> str:
        """条目键归一化（実証 probe4 round2:同一行两跑读出「ターン内/タン内」长音符
        变体致 count 分裂+自一致性误报）——去长音符 ー 后为键。"""
        return text.replace("ー", "")

    @classmethod
    def _merge_panel_items(cls, items: dict[str, int], screen: list[str]) -> None:
        """纯逻辑（可单测）：归一化文本为键合并,count 计数——同名同值重复保留一条+count
        （面板真有两份该状态,信息不丢）,OCR 长音符变体归并为同一键。"""
        for t in screen:
            key = cls._panel_item_key(t)
            items[key] = items.get(key, 0) + 1

    @staticmethod
    def _extract_reprise_from_items(items: dict[str, int]) -> Optional[int]:
        """纯逻辑（可单测）：面板「(再演)」权威行提取剩余 N 回（文字锚零歧义,
        grill R2-Q1 第三源）。行样例実測:「お姉さんの感覚+(再演)」+「3回ターン内0回」。"""
        joined = " ".join(items)
        m = re.search(r"\(再演\).*?(\d+)\s*回", joined)
        return int(m.group(1)) if m else None

    @staticmethod
    def _extract_focus_from_items(items: dict[str, int]) -> Optional[int]:
        """纯逻辑（可单测）：面板「集中 N」条目提取（実測 集中/13 相邻条目）。"""
        keys = [k for k in items if "集中" in k]
        if not keys:
            return None
        m = re.search(r"(\d+)", keys[0])
        return int(m.group(1)) if m else None

    def _close_state_panel(self, context: Context) -> bool:
        for _ in range(3):
            self._click_box_center(context, [337, 740, 47, 34], double=False)  # X 実測中心(360,757)
            time.sleep(1.2)
            if not self._panel_anchor_hit(context, self._get_screenshot(context)):
                return True
        logger.warning("Round1 状态面板关闭失败")
        return False

    def _read_overflow_panel(self, context: Context) -> list[str]:
        """溢出场景入口（兼容保留）：省略号位入口的统一面板法调用。"""
        record = self._read_state_panel(context, self.PANEL_ENTRY_ELLIPSIS)
        return [i["text"] for i in (record or {}).get("items", [])]

    @staticmethod
    def _cluster_buff_words_to_rows(words: list[dict], row_tolerance: int = 15) -> list[dict]:
        """纯逻辑（可单测）：OCR 词框按 y 聚行（同词行容差内合并），行 y=词框 y 中位。"""
        rows: list[dict] = []
        for w in sorted(words, key=lambda w: w["box"][1]):
            y = w["box"][1]
            for row in rows:
                if abs(row["y"] - y) <= row_tolerance:
                    row["words"].append(w["text"])
                    row["y"] = round((row["y"] + y) / 2)
                    break
            else:
                rows.append({"y": y, "words": [w["text"]]})
        return rows

    def _lazy_identify_row(self, context: Context, row_y: int) -> Optional[dict]:
        """懒定案读取（grill R2-Q1：仅 debug 报告不碰 assets/）：点未知行→面板名称+效果→关。"""
        self._click_box_center(context, [7, row_y - 24, 48, 48], double=False)
        time.sleep(self.PANEL_CLICK_DELAY)
        image = self._get_screenshot(context)
        panel = self._run_ocr(context, image, "HIFBuffPanelAnchor", [".*好調.*|.*アビリティ詳細.*"], [100, 40, 420, 140])
        if not (panel and panel.hit):
            return None
        title = self._run_ocr(context, image, "HIFBuffPanelTitle", [".*"], [100, 40, 420, 140])
        body = self._run_ocr(context, image, "HIFBuffPanelBody", [".*"], [40, 150, 460, 560])
        record = {
            "row_y": row_y,
            "title": title.best_result.text.strip() if (title and title.hit) else "",
            "body": [i.text for i in (body.all_results or [])][:10] if body else [],
        }
        for _ in range(3):
            self._click_box_center(context, [330, 730, 55, 45], double=False)
            time.sleep(1.2)
            anchor = self._run_ocr(context, self._get_screenshot(context), "HIFBuffPanelAnchor",
                                   [".*好調.*|.*アビリティ詳細.*"], [100, 40, 420, 140])
            if not (anchor and anchor.hit):
                break
        logger.info(f"Round1 懒定案行@y{row_y}: {record['title'][:30]}")
        return record

    def _enumerate_p_items(self, context: Context, image) -> list[dict]:
        """P item 枚举（右上纵列，数量随局养成增长）：OCR 扫描数字词（N回/N）→ 每个
        数字框 y 定一个 P item（图标在数字左侧同行）+ 触发剩余值。详情读取属懒定案层。"""
        detail = self._run_ocr(context, image, "HIFPItemEnum", [".*"], self.ROI_PITEM_COLUMN)
        items = []
        for i in (detail.all_results or []) if detail else []:
            text = i.text.strip()
            digits = re.sub(r"\D", "", text)
            if digits:
                items.append({"box": list(i.box), "raw": text, "progress_left": int(digits)})
        return items

    # ------------------------------------------------------------------
    # 対局资源全景读取（五轮验证 2026-08-22）：P item 详情弹窗 + 牌堆查看器
    # 実機依据 pitem2_detail.png（debug/autodev/round1，2026-08-21 取证）：
    # P item 弹窗=全部道具效果流式列表，× 关闭 [316,710,86,90] 中心(359,755)
    # 与 buff 面板 X 同位；效果文案均带「(試験・ステージ内N回)」可作锚。
    # ------------------------------------------------------------------

    PITEM_POPUP_CLOSE = (359, 755)                 # × 中心（実機 pitem2_detail OCR）
    PITEM_POPUP_CONTENT_ROI = [40, 40, 640, 660]   # 弹窗内容区（效果文本流式区）
    PITEM_ICON_LEFT_OFFSET = 55                    # 数字框中心 → 图标中心 x 左移（実測纵列）
    PITEM_SCROLL_MAX = 6
    PITEM_CLOSE_CONFIRM = 2                        # 连续 N 次锚仍在 = 关闭失败

    def _pitem_popup_anchor_hit(self, context: Context, image) -> bool:
        """P item 弹窗打开判定：内容区「試験・ステージ」锚（実機両道具均带）。"""
        anchor = self._run_ocr(
            context, image, "HIFPItemPopupAnchor",
            [".*試験.*ステー.*|.*ステージ内.*"], self.PITEM_POPUP_CONTENT_ROI,
        )
        return bool(anchor and anchor.hit)

    # 残留自愈（実機 2026-08-22 轮0）：出牌循环打开的浮层关闭失败会遮挡手牌致
    # read_hand 恒空 → evidence_empty_hand stop。三类浮层：buff 完整面板/P item
    # 弹窗（× 同位 (359,755)，実測 buff X (360,757) 与 pitem × [316,710,86,90]）、
    # P 饮料弹窗（キャンセル左下）。命中锚才点关，验证消失。
    OVERLAY_CLOSE_TAP = (359, 755)

    CARD_DETAIL_ANCHOR = ("スキルカード詳細",)
    CARD_DETAIL_CLOSE = (360, 1180)  # 閉じる按钮(vision 実測 2026-08-22 轮3:点手牌卡
    # 会误开详情弹窗,毛玻璃遮全画面致 turn/hand 全读空 stop)

    def _dissolve_blocking_overlays(self, context: Context) -> bool:
        """探测并关闭遮挡画面的浮层；有任何关闭动作返回 True（调用方重读手牌）。

        四类:buff 面板/P item 弹窗(×同位)/P 饮料弹窗(キャンセル)/スキルカード詳細
        (閉じる)。残留态点击 IPC 丢失高发——循环 4 次+间隔 2s 吸收。"""
        acted = False
        for _ in range(4):
            image = self._get_screenshot(context)
            has_panel = self._panel_anchor_hit(context, image)
            has_pitem = self._pitem_popup_anchor_hit(context, image)
            has_pdrink = self._popup_is_pdrink(context, image)
            has_card_detail = self._find_text_option(context, image, self.CARD_DETAIL_ANCHOR, [20, 80, 400, 120])
            if has_card_detail:
                acted = True
                logger.warning("Round 浮层残留自愈: スキルカード詳細弹窗→閉じる")
                context.tasker.controller.post_click(*self.CARD_DETAIL_CLOSE).wait()
                time.sleep(2.0)
                continue
            has_memab = self._find_text_option(context, image, ("発動予約", "メモリーアビリティ"), [20, 150, 400, 700])
            if not (has_panel or has_pitem or has_pdrink or has_memab):
                break
            acted = True
            logger.warning(
                f"Round 浮层残留自愈: buff面板={has_panel} Pitem弹窗={has_pitem} P饮料弹窗={has_pdrink}"
            )
            if has_pdrink:
                self._close_pdrink_popup(context)
            else:
                self._tap(context, *self.OVERLAY_CLOSE_TAP)
                time.sleep(1.2)
        return acted

    def _read_p_item_details(self, context: Context) -> Optional[list[dict]]:
        """P item 全量详情读取（纯读取）：点纵列图标 → 弹窗（全部道具效果列表）→
        右缘滚动到底（連2無新增+长音符归一，同 _read_state_panel 骨架）→ 词行级
        match_pitem_name 定名 + 效果文本按名字行分段归属 → 关闭验证 → 缓存 session。

        名字行 OCR miss 的段落记 name=None 保 raw（不乱猜，探索轮校准）；
        打不开/点错面板（入口位与 buff 带/排名区交叠会误开 buff 完整面板，
        実機 2026-08-22 轮0 两次 stop 根因）→ 关闭后降级 return None（不 stop）；
        关闭失败也 return None 由调用方残留自愈兜底。
        """
        # 入口：纵列首个数字框左移定图标；纵列空则点 ROI 顶中心兜底
        image = self._get_screenshot(context)
        p_items_seen = self._enumerate_p_items(context, image)
        if p_items_seen:
            bx, by = p_items_seen[0]["box"][0], p_items_seen[0]["box"][1] + p_items_seen[0]["box"][3] // 2
            entry = (max(600, bx - self.PITEM_ICON_LEFT_OFFSET), by)
        else:
            entry = (self.ROI_PITEM_COLUMN[0] + self.ROI_PITEM_COLUMN[2] // 2,
                     self.ROI_PITEM_COLUMN[1] + 40)
        self._click_box_center(context, [entry[0] - 15, entry[1] - 15, 30, 30], double=False)
        time.sleep(self.PANEL_CLICK_DELAY)
        image = self._get_screenshot(context)
        if not self._pitem_popup_anchor_hit(context, image):
            logger.warning("P item 详情弹窗未打开(锚 miss),关闭可能的误开面板后降级跳过")
            self._dissolve_blocking_overlays(context)
            return None

        # 滚动收集全词行（y 排序；連2屏无新增词到底）
        collected: dict[str, dict] = {}
        no_new = 0
        for _ in range(self.PITEM_SCROLL_MAX):
            detail = self._run_ocr(context, image, "HIFPItemDetailWords", [".*"], self.PITEM_POPUP_CONTENT_ROI)
            words = [
                {"text": i.text.strip(), "y": i.box[1], "h": i.box[3]}
                for i in (detail.all_results or []) if i.text.strip()
            ]
            new_words = [w for w in words if self._panel_item_key(w["text"]) not in collected]
            for w in new_words:
                collected[self._panel_item_key(w["text"])] = w
            if not new_words:
                no_new += 1
                if no_new >= self.PANEL_BOTTOM_CONFIRM:
                    break
            else:
                no_new = 0
            self._swipe(context, *self.PANEL_SCROLL_STEP, 400)
            time.sleep(1.3)
            image = self._get_screenshot(context)

        items = self._segment_pitem_words(list(collected.values()))
        if not self._close_pitem_popup(context):
            return None  # 关闭失败=弹窗残留污染画面,整体降级(调用方按 None 处理)
        if items:
            _ProduceHIFActionBase._write_round1_state({"p_items": items})
            self._archive_static(context, "round_p_item_details", {
                "action": "read_p_items", "items": items,
            })
        return items or None

    @staticmethod
    def _segment_pitem_words(words: list[dict]) -> list[dict]:
        """纯逻辑（可单测）：弹窗词行 → P item 分段。名字行=match_pitem_name 命中词；
        效果文本=名字行 y 到下一名字行之间。名字 miss 的头部段落记 name=None。"""
        ordered = sorted(words, key=lambda w: w["y"])
        segments: list[dict] = []
        current: dict | None = None
        for w in ordered:
            name, record = match_pitem_name(w["text"])
            if name is not None:
                if current:
                    segments.append(current)
                current = {
                    "name": name,
                    "raw": w["text"],
                    "progress_left": None,
                    "effects": (record or {}).get("effects"),
                    "ocr_lines": [],  # 效果行从名字行之后开始归属
                }
            else:
                if current is None:
                    current = {"name": None, "raw": w["text"], "progress_left": None, "effects": None, "ocr_lines": []}
                current["ocr_lines"].append(w["text"])
        if current:
            segments.append(current)
        # 纯噪声段（无名字且行数 <2）丢弃
        return [s for s in segments if s["name"] or len(s["ocr_lines"]) >= 2]

    def _close_pitem_popup(self, context: Context) -> bool:
        """关闭 P item 弹窗并验证（× 固定位 + 锚消失验证；実機 × 与 buff 面板同位）。"""
        for _ in range(3):
            self._click_box_center(context, [self.PITEM_POPUP_CLOSE[0] - 20, self.PITEM_POPUP_CLOSE[1] - 15, 40, 30], double=False)
            time.sleep(1.2)
            if not self._pitem_popup_anchor_hit(context, self._get_screenshot(context)):
                return True
        logger.warning("P item 详情弹窗关闭失败")
        return False

    # 牌堆查看器 UI 未実機取证（goal 1.3 裁决：按假设设计、探索轮校准）。
    # 假设：対局页手牌区两侧有山札/捨て札指示器；查看器与変卡网格同构（滚动+词行）。
    PILE_DRAW_TAP = (60, 1150)        # 山札指示器假设位 [待実機校准]
    PILE_DISCARD_TAP = (660, 1150)    # 捨て札指示器假设位 [待実機校准]
    PILE_VIEWER_ROI = [20, 100, 680, 900]  # 查看器内容区假设 [待実機校准]
    PILE_ANCHOR_WORDS = (".*山札.*", ".*捨て札.*", ".*デッキ.*")
    PILE_SCROLL_MAX = 6
    PILE_CLOSE_TAP = (360, 1170)      # 查看器关闭假设位 [待実機校准]

    def _pile_viewer_anchor_hit(self, context: Context, image) -> bool:
        detail = self._find_text_option(context, image, self.PILE_ANCHOR_WORDS, self.PILE_VIEWER_ROI)
        return detail is not None

    def _read_deck_state(self, context: Context) -> Optional[dict]:
        """牌堆全状态读取（纯读取，UI 假设设计待探索轮校准）：点山札指示器 →
        查看器 → 滚动枚举全卡名（词典归一+计数）→ 按锚词分段归属
        （draw/discard/exclude）→ 关闭 → 缓存 session.deck_state。

        查看器打不开（指示器假设位失效）降级 return None 不 stop；
        手牌沿用 ExamStateReader（run 主循环每回合读），此处只补三堆。
        """
        self._click_box_center(context, [self.PILE_DRAW_TAP[0] - 20, self.PILE_DRAW_TAP[1] - 20, 40, 40], double=False)
        time.sleep(self.PANEL_CLICK_DELAY)
        image = self._get_screenshot(context)
        if not self._pile_viewer_anchor_hit(context, image):
            logger.warning("牌堆查看器未打开(指示器假设位 miss),降级跳过")
            return None

        # 滚动收集全部词行（卡名行+堆锚词行）
        lines: list[str] = []
        no_new = 0
        for _ in range(self.PILE_SCROLL_MAX):
            detail = self._run_ocr(context, image, "HIFDeckViewerWords", [".*"], self.PILE_VIEWER_ROI)
            words = [i.text.strip() for i in (detail.all_results or []) if i.text.strip()]
            new_words = [t for t in words if t not in lines]
            lines.extend(new_words)
            if not new_words:
                no_new += 1
                if no_new >= self.PANEL_BOTTOM_CONFIRM:
                    break
            else:
                no_new = 0
            self._swipe(context, *self.PANEL_SCROLL_STEP, 400)
            time.sleep(1.3)
            image = self._get_screenshot(context)

        deck = self._segment_pile_lines(lines)
        self._close_pile_viewer(context)
        if deck:
            _ProduceHIFActionBase._write_round1_state({"deck_state": deck})
            self._archive_static(context, "round_deck_state", {"action": "read_deck", "deck": deck})
        return deck or None

    @staticmethod
    def _segment_pile_lines(lines: list[str]) -> dict:
        """纯逻辑（可单测）：查看器词行 → {draw,discard,exclude,hand:[]}。
        锚词（山札/捨て札・捨札/除外）后段归属对应堆；无锚头部归 draw；
        卡名经 normalize_card_name 归一（+档保留），非卡名噪声行丢弃。"""
        piles: dict[str, list[str]] = {"draw": [], "discard": [], "exclude": [], "hand": []}
        current = "draw"
        for text in lines:
            compact = text.replace(" ", "")
            if "山札" in compact:
                current = "draw"
                continue
            if "捨て札" in compact or "捨札" in compact:
                current = "discard"
                continue
            if "除外" in compact:
                current = "exclude"
                continue
            name = normalize_card_name(compact)
            # 卡名有效性（同変卡 _read_cell_name 噪声口径）：含日文且 ≥4 字
            if len(name) >= 4 and any("\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff" for ch in name):
                piles[current].append(name)
        return piles

    def _close_pile_viewer(self, context: Context) -> bool:
        for _ in range(3):
            self._tap(context, *self.PILE_CLOSE_TAP)
            time.sleep(1.2)
            if not self._pile_viewer_anchor_hit(context, self._get_screenshot(context)):
                return True
        logger.warning("牌堆查看器关闭失败(假设位,探索轮校准)")
        return False
