import re
import json
import time
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
from agent.hif.decisions.scoring import DecisionContext, score_card_by_name, score_drink_by_name
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
        cls._write_session_state({
            cls.ROUND1_STATE_KEY: {
                "turn": 0,
                "cards_played": 0,
                "oneesan_used": False,
                "natural_finisher_used": False,
                "reprise_count": 0,
            }
        })

    @staticmethod
    def _get_screenshot(context: Context):
        return context.tasker.controller.post_screencap().wait().get()

    @staticmethod
    def _click_box_center(context: Context, box: List[int], double: bool = True, y_offset: int = 0) -> bool:
        if not box or len(box) < 4:
            return False

        x = box[0] + box[2] // 2
        y = box[1] + box[3] // 2 + y_offset
        context.tasker.controller.post_click(x, y).wait()
        if double:
            time.sleep(_ProduceHIFActionBase.CLICK_DELAY)
            context.tasker.controller.post_click(x, y).wait()
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
    ) -> Dict[str, Any]:
        """组装 Round1 出牌落盘记录（F3，纯函数可离线单测）。

        前六字段对齐 roundsim ManualTurnRecord（turn/flow/played_cards/good_condition_turns/
        stamina/turn_score，実機手记口径，供 tools/hif_replay_report.py 回放对比）；
        后五字段为実機执行层扩展（action/target_card/reason/dry_run/evidence，
        evidence 含点击 box 坐标与 OCR 原文）。缺省字段显式带 None/[]/{}，
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
            "evidence": evidence or {},
        })
        return record

    @classmethod
    def _archive_round1_play(cls, image, record: dict) -> None:
        """Round1 出牌决策落盘（F3，Phase 2 ProduceHIFRound1Play 每回合调用）。

        先按 ROUND1_PLAY_RECORD_FIELDS 做防御性重排（调用方乱序/缺键也输出
        schema 稳定的记录，extra 键保留在后），再走共用存档链
        （截图 + session JSONL + viewer 刷新，与 _archive_decision 同模式）。
        """
        ordered = {key: record.get(key) for key in ROUND1_PLAY_RECORD_FIELDS}
        for key, value in record.items():
            if key not in ordered:
                ordered[key] = value
        cls._archive_decision(image, cls.ROUND1_PLAY_SCREEN, ordered)


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

    def _choose_first_safe_option(self, context: Context, image) -> bool:
        reco_detail = self._run_ocr(context, image, "ProduceRecognitionHIFClassOptions", [".*"], self.OPTION_ROI)
        if not (reco_detail and reco_detail.all_results):
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
            context.tasker.controller.post_click(*self.BLANK_TAP).wait()
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
        self._click_box_center(context, box, double=False)
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
        reroll = preset.select_change_reroll_override or preset.select_change_reroll_limit
        return self._choose_keyword_reward(context, preset, reroll_limit=reroll, screen_state="select_change_target")


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
    SCROLL_TO = (360, 740)  # 300px = 2 行对齐滚动
    MAX_SCREENS = 4
    CELL_CLICK_DELAY = 1.6
    FALLBACK_MAX_TRIES = 4  # トラブル格按钮不亮时的顺延重试上限

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
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

        判底（実機 13:34 复盘：单格探针会被滚动重叠误判「到底」——300px 滚 2 行
        必有重叠行）改为首行 3 格探针签名：全部 ∈ 已见集合才算真到底。
        """
        entries: list[dict] = []
        for screen in range(self.MAX_SCREENS):
            for ri, y in enumerate(self.GRID_ROWS, 1):
                for ci, x in enumerate(self.GRID_COLS, 1):
                    name = self._read_cell_name_after_click(context, x, y)
                    entries.append({"screen": screen, "cell": f"s{screen}r{ri}c{ci}", "xy": [x, y], "name": name})
                    logger.debug(f"HIF 変卡扫描: s{screen}r{ri}c{ci} = {name!r}")
            if screen < self.MAX_SCREENS - 1:
                seen = {e["name"] for e in entries if e["name"]}
                context.tasker.controller.post_swipe(*self.SCROLL_FROM, *self.SCROLL_TO, duration=300).wait()
                time.sleep(self.ACTION_DELAY)
                probe_row = [self._read_cell_name_after_click(context, x, self.GRID_ROWS[0])
                             for x in self.GRID_COLS[:3]]
                if all(p and p in seen for p in probe_row):
                    break  # 首行签名完全重复 = 真到底
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
            context.tasker.controller.post_swipe(*self.SCROLL_TO, *self.SCROLL_FROM, duration=300).wait()
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
            context.tasker.controller.post_swipe(*self.SCROLL_FROM, *self.SCROLL_TO, duration=300).wait()
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
                context.tasker.controller.post_click(*self.POPUP_OK_TAP).wait()
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
                context.tasker.controller.post_click(x, y).wait()
                time.sleep(self.ACTION_DELAY)
                new_remain = self._read_digits_text(context, self._get_screenshot(context))
                if new_remain is None:
                    return self._stop_unsupported(context, "hif_drink_overflow", "remain_counter_lost_after_tap")
                if new_remain > remain:
                    # 颜色误判点中已勾框:撤销勾选并放弃该框
                    context.tasker.controller.post_click(x, y).wait()
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
                context.tasker.controller.post_swipe(360, 900, 360, 500, duration=300).wait()
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
        context.tasker.controller.post_click(*self.BLANK_TAP).wait()
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
    ROI_TURN = [35, 60, 55, 55]        # 残りターン数值（3.3.0 校准 2026-08-21：左界 25 引入
    # 仪表盘刻度噪声致 9→a 误读 0.37，收窄后 1.0；杂讯 M/• 靠整数提取跳过）
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
    EVIDENCE_RETRY = 2        # 手牌读空重试次数（Q12 禁盲点）

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        preset = self._get_preset(argv)
        if preset.round1_mode != "play":
            return self._stop_unsupported(context, "round1_play", "round1_mode_not_play")

        _ProduceHIFActionBase._reset_round1_state()
        played_history: List[str] = []
        no_progress = 0
        logger.success("HIF Round1 出牌开始（play 模式）")
        # 开局全量一次（grill R1-Q1 分层）：集中面板缓存（R1-Q4b 兜底）
        focus_cached = self._read_focus_from_panel(context)
        logger.info(f"Round1 开局面板读集中={focus_cached}")
        # P 饮料槽探测（R1-Q1/R2：槽位前缀固定，点开弹窗实锤，缓存 session）
        p_drink_slots = self._probe_p_drink_slots(context)
        logger.info(f"Round1 P饮料槽探测={self._available_drinks_from_slots(p_drink_slots)}")

        while True:
            image = self._get_screenshot(context)
            turn_left = self._read_turn_left(context, image)
            if turn_left is None:
                # 动画/转场窗口重试一次（実機首跑：面板关闭动画内截图致读空误停）
                time.sleep(self.ACTION_DELAY)
                image = self._get_screenshot(context)
                turn_left = self._read_turn_left(context, image)
            if turn_left is None:
                return self._stop_unsupported(context, "round1_play", "turn_counter_unreadable")
            if turn_left == 0:
                logger.success(f"HIF Round1 出牌完成：共出 {len(played_history)} 张")
                return True

            hand = ExamStateReader.from_context(context).read_hand()
            if not hand.card_names:
                if not self._wait_transition(context, turn_left):
                    no_progress += 1
                    if no_progress >= self.NO_PROGRESS_LIMIT:
                        return self._stop_unsupported(context, "round1_play", "evidence_empty_hand")
                    continue
                continue
            no_progress = 0

            state = self._build_state(context, image, turn_left, hand)
            evidence = self._collect_evidence(context, image, turn_left)
            evidence["hand"] = list(hand.card_names)
            action = GarakutaRinamiStrategy(ProfilePayload.default()).decide(state)
            logger.info(
                f"Round1 turn={state.turn} 残り{turn_left} gc={state.good_condition_turns} "
                f"focus={state.focus} stamina={state.stamina} flow={state.current_flow} "
                f"score={evidence.get('total_score')} → {action.kind.value}"
                f"{('/' + action.target_card) if action.target_card else ''}"
            )

            if action.kind is ActionKind.USE_P_DRINK:
                # Q9+A5:瓶位语义未定案,拦截只记录,降级 SKIP 回体(禁猜测性点击)
                logger.warning(f"Round1 USE_P_DRINK 拦截(记录不点): {action.target_card}")
                self._archive_round1_play(image, self.build_round1_play_record(
                    state, action, played_history[-1:], dry_run=True,
                    evidence={**evidence, "intercepted": "p_drink_semantics_undefined"},
                ))
                action = CardAction(ActionKind.SKIP, None, f"[P饮料拦截降级] {action.reason}")

            ok, played_card = self._execute_action(context, action, hand)
            if not ok:
                no_progress += 1
                if no_progress >= self.NO_PROGRESS_LIMIT:
                    return self._stop_unsupported(context, "round1_play", "action_execute_failed")
                continue

            if played_card:
                played_history.append(played_card)
                self._record_session_progress(played_card)

            self._archive_round1_play(image, self.build_round1_play_record(
                state, action, [played_card] if played_card else [],
                turn_score=evidence.get("total_score"), evidence=evidence,
            ))

            # 等回合转场（残りターン变化）；未变化则继续同回合下一步
            self._wait_transition(context, turn_left)

    # ------------------------------------------------------------------
    # 画面读取（Q6 画面优先；读不到回退 session/默认值并告警）
    # ------------------------------------------------------------------

    def _read_turn_left(self, context: Context, image) -> Optional[int]:
        detail = self._run_ocr(
            context, image, "HIFRound1TurnLeft", [".*"], self.ROI_TURN,
        )
        if not (detail and detail.hit):
            return None
        digits = re.sub(r"\D", "", detail.best_result.text)
        return int(digits) if digits else None

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

    def _read_total_score(self, context: Context, image) -> Optional[int]:
        """右上総分 → turn_score 落盘来源。実測 ROI 内含邻位小数字（70/0），
        best_result 会选错框——取 all_results 最大数值（総分单调增且远大于邻数）。"""
        detail = self._run_ocr(context, image, "HIFRound1TotalScore", [".*"], self.ROI_TOTAL_SCORE)
        if not (detail and detail.hit):
            return None
        values = []
        for item in (detail.all_results or []):
            digits = re.sub(r"\D", "", item.text)
            if digits:
                values.append(int(digits))
        return max(values) if values else None

    def _read_focus_from_panel(self, context: Context) -> Optional[int]:
        """集中面板法（grill R1-Q4b 兜底）：点好調行开组合面板 → OCR 集中条目
        （実機 2026-08-21 锚：标题 y246/值 y285，ROI [100,230,300,130]）→ 关面板。
        集中状态带模板本局 MISS（图标样式随局异动），面板法开局读一次缓存 session。
        実機首跑教训：开/关都要验证（面板没开读到 None、没关挡住 turn ROI——
        关闭动画窗口内主循环截图致 turn_counter_unreadable 误停）。"""
        value = None
        for dy in (0, -12, 12):
            self._click_box_center(context, [7, 253 + dy, 48, 48], double=False)
            time.sleep(self.PANEL_CLICK_DELAY)
            image = self._get_screenshot(context)
            panel = self._run_ocr(context, image, "HIFRound1PanelAnchor", [".*好調.*"], [100, 40, 420, 140])
            if not (panel and panel.hit):
                continue  # 面板没开，微调 y 重试
            focus = self._run_ocr(context, image, "HIFRound1FocusPanel", [".*集中.*"], [100, 230, 300, 130])
            if focus and focus.hit:
                # 実測「集中」标题(y246)与数值(y285)是两个独立 OCR 框,best_result 只含
                # 标题二字——数值行单独读（[100,275,300,50] 実測校准）
                num = self._run_ocr(context, image, "HIFRound1FocusPanelNum", [".*"], [100, 275, 300, 50])
                source_text = (num.best_result.text if (num and num.hit) else "") or focus.best_result.text
                digits = re.sub(r"\D", "", source_text)
                value = int(digits) if digits else None
            break
        # 关面板并验证真关（title 区「好調」锚消失）
        for _ in range(3):
            self._click_box_center(context, [330, 730, 55, 45], double=False)  # 面板底部 ×(357,753)
            time.sleep(1.2)
            image = self._get_screenshot(context)
            panel = self._run_ocr(context, image, "HIFRound1PanelAnchor", [".*好調.*"], [100, 40, 420, 140])
            if not (panel and panel.hit):
                break
        if value is not None:
            _ProduceHIFActionBase._write_round1_state({"focus_cached": value})
        return value

    def _build_state(self, context: Context, image, turn_left: int, hand) -> ExamState:
        session = _ProduceHIFActionBase._read_round1_state()
        good = self._read_buff_turns(context, image, self.TPL_GOOD)
        focus = self._read_buff_turns(context, image, self.TPL_CONC)
        if focus is None:
            # 集中双保险（grill R1-Q4）：状态带模板 MISS 时用开局面板缓存+告警
            focus = int(session.get("focus_cached") or 0) or None
            if focus is not None:
                logger.info(f"集中模板 MISS，用面板缓存={focus}")
        reprise_used = self._read_reprise_used(context, image)
        if good is None:
            logger.warning(f"好調行模板定行失败，session 兜底={session.get('good_condition_turns')}")
        if reprise_used is not None:
            # 双源告警（R1-Q5）：旧源右上 N 回实为 P item 剩余，实测 diff 定案前保留+告警
            logger.warning(f"reprise 旧源(右上,疑 P item 误标)={reprise_used}, 出牌 diff 后切换新源")
        return ExamState(
            round=ExamRound.HONSEN_R1,
            turn=self.TOTAL_TURNS - turn_left + 1,
            total_turns=self.TOTAL_TURNS,
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
            available_p_drinks=self._available_drinks_from_slots(session.get("p_drink_slots") or []),
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

    def _execute_action(self, context: Context, action: CardAction, hand) -> tuple[bool, Optional[str]]:
        if action.kind is ActionKind.SKIP:
            return self._click_skip(context), None

        target = (normalize_card_name(action.target_card).rstrip("+")
                  if action.target_card else None)
        reader = ExamStateReader.from_context(context)
        detections = reader.ocr.run_yolo_cards()
        chosen = None
        for d in detections:
            name = normalize_card_name(d.card_name).rstrip("+") if d.card_name else ""
            if target and name == target:
                chosen = d
                break
            if not target and name:
                chosen = chosen or d  # target=None 时按 YOLO 顺序取首张可读卡
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
            context.tasker.controller.post_click(*self.CLICK_SKIP).wait()
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

    def _wait_transition(self, context: Context, prev_turn_left: int) -> bool:
        """等待回合转场：残りターン变化（实测 <2s，轮询到 60s 超时，Q13）。"""
        deadline = time.time() + self.TRANSITION_TIMEOUT_S
        while time.time() < deadline:
            time.sleep(2.0)
            image = self._get_screenshot(context)
            turn_left = self._read_turn_left(context, image)
            if turn_left is not None and turn_left != prev_turn_left:
                return True
        logger.warning(f"Round1 转场超时 {self.TRANSITION_TIMEOUT_S}s（残りターン未变化）")
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
        """用药复核读取（grill R2-Q2 前半，纯读取不使う）：点槽→弹窗验证→读名→关→验证关。"""
        self._click_box_center(context, [slot_xy[0] - 20, slot_xy[1] - 20, 40, 40], double=False)
        time.sleep(self.PANEL_CLICK_DELAY)
        image = self._get_screenshot(context)
        if not self._popup_is_pdrink(context, image):
            return None  # 空槽/槽不存在（同语义，grill R2 用户确认）
        name_detail = self._run_ocr(context, image, "HIFPDrinkName", [".*"], self.PDRINK_NAME_ROI)
        name = name_detail.best_result.text.strip() if (name_detail and name_detail.hit) else ""
        self._close_pdrink_popup(context)
        return name or None

    def _probe_p_drink_slots(self, context: Context) -> list[dict]:
        """开局槽探测（grill R1-Q1/R2 用户确认：槽位前缀固定，点开弹窗为实锤）。
        结果缓存 session.p_drink_slots；空槽/槽不存在同记 empty。"""
        slots = []
        for i, xy in enumerate(self.PDRINK_SLOTS, 1):
            name = self._verify_p_drink(context, xy)
            slots.append({"slot": i, "xy": list(xy), "name": name})
            logger.info(f"Round1 P饮料槽{i}: {name or '(empty)'}")
        _ProduceHIFActionBase._write_round1_state({"p_drink_slots": slots})
        return slots

    @classmethod
    def _available_drinks_from_slots(cls, slots: list[dict]) -> list[str]:
        """纯逻辑（可单测）：缓存槽表 → available_p_drinks 名单（去空+保持槽序）。"""
        return [s["name"] for s in slots if s.get("name")]

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
        return rows

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
