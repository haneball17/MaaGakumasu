"""通过 ADB 运行正式 HIF 路由，并保存可复盘的实机证据。"""

from __future__ import annotations

import sys
import copy
import json
import time
import argparse
from typing import Any
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
for import_path in (ROOT, ROOT / "agent"):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from agent.hif.runtime import get_image_size, validate_hif_frame
from agent.hif.image_io import save_hif_image


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从正式节点运行 HIF 实机管线，并保存运行前后截图与 Maa 日志")
    parser.add_argument("--adb", required=True, help="MuMu ADB 地址，例如 127.0.0.1:16416")
    parser.add_argument("--adb-path", type=Path, required=True, help="MuMu 自带 adb.exe 的绝对路径")
    parser.add_argument("--task", default="ProduceEntryHIF", help="正式 Pipeline 入口节点")
    parser.add_argument("--seconds", type=float, default=30.0, help="单次运行最长秒数")
    parser.add_argument("--single-step", action="store_true", help="仅启用已审阅的 HIF 单步节点；Round 与技能卡领取保持停止")
    parser.add_argument(
        "--round1-deck-probe",
        action="store_true",
        help="仅在 --single-step 下打开持有技能卡列表读取数量并关闭；保持影子决策，不出牌",
    )
    parser.add_argument(
        "--round1-hand-detail-probe",
        action="store_true",
        help="仅在 --single-step 下逐张单击手牌读取详情标题；不点击 SELECT，最后一张保持选中",
    )
    parser.add_argument(
        "--round1-hand-detail-probe-from-selected",
        action="store_true",
        help="仅从已验证 SELECT 的页面恢复：零点击记录当前牌，再逐张切换其余手牌",
    )
    parser.add_argument(
        "--round1-hand-detail-map-observe",
        action="store_true",
        help="同一进程内用详情标题补齐五卡手牌 OCR 后仅记录完整性，不出牌",
    )
    parser.add_argument(
        "--round1-hand-detail-map-deck-observe",
        action="store_true",
        help="同一进程内完成详情映射和牌库读取后只记录完整状态与策略，不出牌",
    )
    parser.add_argument(
        "--round1-hand-detail-map-deck-observe-from-selected",
        action="store_true",
        help="从已选详情态完成手牌映射和牌库读取，仅记录完整状态与策略，不出牌",
    )
    parser.add_argument(
        "--round1-hand-detail-map-deck-select-one-from-selected",
        action="store_true",
        help="从已选详情态完成映射后，仅选择一张经严格策略批准的卡，不确认出牌",
    )
    parser.add_argument(
        "--round1-hand-detail-map-deck-play-one",
        action="store_true",
        help="同一进程内完成五张手牌详情映射与牌库读取，仅在完整受限审批后执行話題沸騰",
    )
    parser.add_argument(
        "--round1-hand-detail-map-deck-select-presence",
        action="store_true",
        help="仅用于已授权的存在感：完成详情映射和牌库读取后只进行首次选择，不确认出牌",
    )
    parser.add_argument(
        "--round1-selected-card-detail-probe",
        action="store_true",
        help="零点击读取当前已选中手牌的详情标题并停止",
    )
    parser.add_argument(
        "--round1-turn-roi-probe",
        action="store_true",
        help="零点击比较多组剩余回合 ROI 的 OCR 原文与置信度",
    )
    parser.add_argument(
        "--round1-counter-roi-probe",
        action="store_true",
        help="零点击读取 Round1 再演/使用次数候选区域；仅采证，不恢复状态或出牌",
    )
    parser.add_argument(
        "--round1-status-detail-slot",
        type=int,
        choices=range(3, 10),
        help="只读打开指定左侧状态行(3-9)的详情，记录 OCR 后原位关闭",
    )
    parser.add_argument(
        "--round1-status-detail-close",
        action="store_true",
        help="从已打开的效果详情弹窗点击明确的閉じる并验证恢复 Round1",
    )
    parser.add_argument(
        "--round1-status-effect-probe",
        choices=("消費体力減少",),
        help="从效果列表按完整名称打开指定状态详情，记录后逐层关闭",
    )
    parser.add_argument(
        "--round1-details-observe",
        action="store_true",
        help="仅打开并关闭已校准的 Round1 详情面板，读取分数/审查基准/倍率；不选牌、不出牌",
    )
    parser.add_argument(
        "--round1-state-observe",
        action="store_true",
        help="隔离根路由后零点击读取 Round1 完整状态与影子决策",
    )
    parser.add_argument(
        "--round1-play-one",
        action="store_true",
        help="仅在 --single-step 下读取牌库并执行一张唯一目标牌；语义后验后立即停止",
    )
    parser.add_argument(
        "--round1-confirm-selected",
        action="store_true",
        help="恢复显式绑定的已选卡：验证标题与 SELECT 后执行第二次点击并停止",
    )
    parser.add_argument(
        "--round1-confirm-selected-name",
        choices=("至高のエンタメ", "お姉さんの感覚", "仕切り直し", "アイドル宣言", "存在感"),
        help="与 --round1-confirm-selected 一起使用；默认仍为至高のエンタメ",
    )
    parser.add_argument(
        "--round1-play-one-after-entertainment",
        action="store_true",
        help="仅在已验证至高のエンタメ首牌后恢复 reprise=0，读取牌库并单步执行下一唯一目标",
    )
    source_probe_group = parser.add_mutually_exclusive_group()
    source_probe_group.add_argument(
        "--source-deck-probe",
        action="store_true",
        help="仅在 --single-step 下点击源卡牌库首张可见卡读取详情后停止；不滚动、不点チェンジ",
    )
    source_probe_group.add_argument(
        "--source-deck-enumerate-visible",
        action="store_true",
        help="仅在 --single-step 下枚举当前可见的 12 个源卡槽位后停止；不滚动、不点チェンジ",
    )
    source_probe_group.add_argument(
        "--source-deck-scroll-enumerate-visible",
        action="store_true",
        help="仅在 --single-step 下向上滑动一次后枚举可见源卡槽位；不点チェンジ",
    )
    source_probe_group.add_argument(
        "--source-deck-enumerate-all",
        action="store_true",
        help="仅在 --single-step 下分页枚举至牌库到底；不点チェンジ",
    )
    source_probe_group.add_argument(
        "--source-deck-confirm-target",
        action="store_true",
        help="仅在 --single-step 下重选已实测的大胆不敵并提交チェンジ；必须通过结果文本后验",
    )
    source_probe_group.add_argument(
        "--source-deck-cancel-to-target",
        action="store_true",
        help="仅在 --single-step 下点击源卡页的キャンセル并验证返回目标三选页",
    )
    parser.add_argument("--source-deck-confirm-name", help="经用户明确授权的源卡名；仅能与 --source-deck-confirm-target 一起使用")
    parser.add_argument(
        "--source-deck-confirm-slot",
        choices=("r1c1", "r1c2", "r1c3", "r1c4", "r2c1", "r2c2", "r2c3", "r2c4", "r3c1", "r3c2", "r3c3", "r3c4"),
        help="经实机枚举确认的源卡槽位；仅能与 --source-deck-confirm-target 一起使用",
    )
    parser.add_argument(
        "--source-deck-confirm-scroll-once",
        action="store_true",
        help="仅与 --source-deck-confirm-target 一起使用；确认前复现一次已验证的向上滑动",
    )
    parser.add_argument(
        "--select-change-target-name",
        help="单步实机中由用户明确指定的变卡目标；不修改默认预设优先级",
    )
    parser.add_argument(
        "--select-change-target-enumerate",
        action="store_true",
        help="仅在 --single-step 下枚举三个变卡目标后停止；不重抽、不点次へ",
    )
    parser.add_argument(
        "--skill-reward-enumerate",
        action="store_true",
        help="仅在 --single-step 下临时选中三张技能卡候选并读取详情；不重抽、不领取、不进入 Round",
    )
    parser.add_argument(
        "--skill-reward-decide",
        action="store_true",
        help="仅在 --single-step 下枚举三张技能卡并记录唯一评分结果；不重选、不领取、不进入 Round",
    )
    parser.add_argument(
        "--skill-reward-receive",
        action="store_true",
        help="仅在 --single-step 下枚举、重选并领取唯一技能卡；领取后必须命中 Round1，不能与其他技能卡探针并用",
    )
    parser.add_argument(
        "--skill-reward-reveal-confirm",
        action="store_true",
        help="仅在 --single-step 下确认已领取技能卡的展示层；需要显式卡名且点击后必须命中 Round1",
    )
    parser.add_argument("--skill-reward-reveal-name", help="展示层确认的已领取技能卡名")
    parser.add_argument(
        "--drink-overflow-keep-black-vinegar",
        action="store_true",
        help="仅在 --single-step 下处理已校准的饮料满仓恢复：保留“消費体力を0にする”的初星黒酢",
    )
    consult_probe_group = parser.add_mutually_exclusive_group()
    consult_probe_group.add_argument("--consult-observe-enhance", action="store_true", help="仅打开咨询的强化页并记录后停止；不选卡、不强化")
    consult_probe_group.add_argument("--consult-observe-delete", action="store_true", help="仅打开咨询的删除页并记录后停止；不选卡、不删除")
    parser.add_argument(
        "--skill-reward-initial-slot",
        choices=("left", "center", "right"),
        help="已知当前已选中的技能卡槽位；仅与技能卡枚举、纯决策或受限领取一起使用，避免重复点击该槽",
    )
    parser.add_argument("--hif-from-home", action="store_true", help="从 Produce 入口按任务配置选择 HIF，并进入正式 HIF 准备链")
    parser.add_argument("--run-id", help="证据目录名称；默认使用本地时间")
    return parser.parse_args(argv)


def _load_custom_types(package_name: str, base_type: type) -> dict[str, type]:
    """从项目导出清单加载可注册的 Custom 类型，避免遗漏通用入口依赖。"""

    package = __import__(package_name, fromlist=["__all__"])
    registered: dict[str, type] = {}
    for name in getattr(package, "__all__", ()):
        candidate = getattr(package, name, None)
        if isinstance(candidate, type) and issubclass(candidate, base_type):
            registered[name] = candidate
    return registered


def load_custom_actions() -> dict[str, type]:
    from maa.custom_action import CustomAction

    actions = _load_custom_types("agent.custom.action", CustomAction)
    # AgentServer 装饰器会切换进程全局 DLL 模式；运行器持有 Resource，必须恢复 Framework 模式。
    from maa.library import Library

    Library._is_agent_server = False
    return actions


def load_custom_recognitions() -> dict[str, type]:
    from maa.custom_recognition import CustomRecognition

    recognitions = _load_custom_types("agent.custom.reco", CustomRecognition)
    from maa.library import Library

    Library._is_agent_server = False
    return recognitions


def single_step_override() -> dict[str, dict[str, Any]]:
    """实验模式只授权经实测验证的日程、授業预览、变卡目标、过渡和 P 饮料领取。"""

    params = {"preset_id": "rinami_good_condition_safe", "execution_mode": "single_step"}
    return {
        node: {"action": {"param": {"custom_action_param": params}}}
        for node in (
            "ProduceChooseDifficulty",
            "ProduceHIFStartConfirmFlag",
            "ProduceChooseHIFEventFlag",
            "ProduceHIFClassOptionFlag",
            "ProduceHIFPublicLessonResultFlag",
            "ProduceHIFSelectChangeTargetFlag",
            "ProduceHIFGiftBagsFlag",
            "ProduceHIFGiftRewardResultFlag",
            "ProduceHIFSkillEnhancedResultFlag",
            "ProduceHIFConsultFlag",
            "ProduceHIFFinalsRankingFlag",
            "ProduceHIFSafeAdvanceFlag",
            "ProduceHIFDrinkRewardFlag",
            "ProduceHIFDrinkRewardRevealFlag",
            "ProduceHIFRewardConfirmFlag",
        )
    }


def source_deck_probe_override(mode: bool | str = True) -> dict[str, dict[str, Any]]:
    """仅为源卡详情采样打开受限开关，不能授权确认或滚动。"""

    return {
        "ProduceHIFSelectChangeSourceFlag": {
            "action": {
                "param": {
                    "custom_action_param": {
                        "preset_id": "rinami_good_condition_safe",
                        "execution_mode": "single_step",
                        "source_deck_probe": mode,
                    }
                }
            }
        }
    }


def skill_reward_probe_override(
    probe: str, initial_slot: str | None = None, *, isolate_root: bool = True
) -> dict[str, dict[str, Any]]:
    """仅开启技能卡候选枚举或纯决策；从当前奖励页启动时隔离通用页面探测分支。"""

    params: dict[str, Any] = {
        "preset_id": "rinami_good_condition_safe",
        "execution_mode": "single_step",
        "skill_reward_probe": probe,
    }
    if initial_slot:
        params["skill_reward_initial_slot"] = f"candidate_{initial_slot}"
    override = {
        node: {
            "action": {
                "param": {
                    "custom_action_param": params
                }
            }
        }
        for node in ("ProduceHIFSkillRewardFlag", "ProduceHIFSkillRewardSelectedFlag")
    }
    if isolate_root:
        # 通用 ProduceExit 识别失败时会调用 Click_1。当前奖励页的技能卡实验仅允许
        # 已确认的奖励页路由，避免为了探测无关页面而产生额外输入。
        override["ProduceEntryHIF"] = {
            "next": [
                "[JumpBack]ProduceHIFSkillRewardSelectedFlag",
                "[JumpBack]ProduceHIFSkillRewardFlag",
                "ProduceHIFUnknownStop",
            ]
        }
    return override


def skill_reward_receive_override(
    initial_slot: str | None = None, *, isolate_root: bool = True
) -> dict[str, dict[str, Any]]:
    """为一次受限技能卡领取同时注入选择和确认的显式授权。"""

    override = skill_reward_probe_override("receive_selected", initial_slot, isolate_root=isolate_root)
    for node in ("ProduceHIFSkillRewardFlag", "ProduceHIFSkillRewardSelectedFlag"):
        override[node]["action"]["param"]["custom_action_param"]["skill_reward_receive_authorized"] = True
    override["ProduceHIFSkillRewardRevealFlag"] = {
        "action": {
            "param": {
                "custom_action_param": {
                    "preset_id": "rinami_good_condition_safe",
                    "execution_mode": "single_step",
                    "skill_reward_receive_authorized": True,
                }
            }
        }
    }
    if isolate_root:
        override["ProduceEntryHIF"]["next"].insert(0, "[JumpBack]ProduceHIFSkillRewardRevealFlag")
    override["ProduceHIFRewardConfirmFlag"] = {
        "action": {
            "param": {
                "custom_action_param": {
                    "preset_id": "rinami_good_condition_safe",
                    "execution_mode": "single_step",
                    "skill_reward_receive_authorized": True,
                }
            }
        }
    }
    return override


def skill_reward_reveal_override(skill_name: str) -> dict[str, dict[str, Any]]:
    """恢复已领取技能卡展示层时，限定为已核验卡名与 Round1 后验。"""

    return {
        "ProduceHIFSkillRewardRevealFlag": {
            "action": {
                "param": {
                    "custom_action_param": {
                        "preset_id": "rinami_good_condition_safe",
                        "execution_mode": "single_step",
                        "skill_reward_receive_authorized": True,
                        "skill_reward_reveal_expected_name": skill_name,
                    }
                }
            }
        },
        "ProduceEntryHIF": {
            "next": ["[JumpBack]ProduceHIFSkillRewardRevealFlag", "ProduceHIFUnknownStop"]
        },
    }


def hif_from_home_override() -> dict[str, Any]:
    """读取任务定义中的 HIF 场景覆盖，保持实机入口与用户界面配置一致。"""

    task_path = ROOT / "assets" / "tasks" / "produce.json"
    payload = json.loads(task_path.read_text(encoding="utf-8"))
    difficulty = payload["option"]["培育难度"]
    hif_case = next(case for case in difficulty["cases"] if case["name"] == "HIF")
    return dict(hif_case["pipeline_override"])


def runtime_override(args: argparse.Namespace) -> dict[str, Any] | None:
    override: dict[str, Any] = {}
    if args.hif_from_home:
        override = _deep_merge(override, hif_from_home_override())
    if args.single_step:
        override = _deep_merge(override, single_step_override())
    round1_modes = sum(
        (
            args.round1_deck_probe,
            args.round1_hand_detail_probe,
            args.round1_hand_detail_probe_from_selected,
            args.round1_hand_detail_map_observe,
            args.round1_hand_detail_map_deck_observe,
            args.round1_hand_detail_map_deck_observe_from_selected,
            args.round1_hand_detail_map_deck_select_one_from_selected,
            args.round1_hand_detail_map_deck_play_one,
            args.round1_hand_detail_map_deck_select_presence,
            args.round1_selected_card_detail_probe,
            args.round1_turn_roi_probe,
            args.round1_counter_roi_probe,
            args.round1_status_detail_slot is not None,
            args.round1_status_detail_close,
            args.round1_status_effect_probe is not None,
            args.round1_details_observe,
            args.round1_state_observe,
            args.round1_play_one,
            args.round1_confirm_selected,
            args.round1_play_one_after_entertainment,
        )
    )
    if round1_modes > 1:
        raise ValueError("Round1 牌库观察、单张出牌与已选卡确认模式不能同时启用")
    if args.round1_hand_detail_probe:
        if not args.single_step:
            raise ValueError("Round1 手牌详情探针必须与 --single-step 一起使用")
        override = _deep_merge(
            override,
            {
                "ProduceHIFRound1ActionFlag": {
                    "action": {
                        "param": {
                            "custom_action_param": {
                                "preset_id": "rinami_good_condition_safe",
                                "round": "round1",
                                "execution_mode": "observe_and_stop",
                                "round_probe": "hand_details",
                                "round_probe_execution_mode": "single_step",
                            }
                        }
                    }
                },
                "ProduceEntryHIF": {"next": ["[JumpBack]ProduceHIFRound1Flag", "ProduceHIFUnknownStop"]},
            },
        )
    if args.round1_hand_detail_probe_from_selected:
        if not args.single_step:
            raise ValueError("Round1 已选中手牌详情探针必须与 --single-step 一起使用")
        override = _deep_merge(
            override,
            {
                "ProduceHIFRound1ActionFlag": {
                    "action": {
                        "param": {
                            "custom_action_param": {
                                "preset_id": "rinami_good_condition_safe",
                                "round": "round1",
                                "execution_mode": "observe_and_stop",
                                "round_probe": "hand_details_selected",
                                "round_probe_execution_mode": "single_step",
                            }
                        }
                    }
                },
                "ProduceEntryHIF": {"next": ["[JumpBack]ProduceHIFRound1Flag", "ProduceHIFUnknownStop"]},
            },
        )
    if args.round1_hand_detail_map_observe:
        if not args.single_step:
            raise ValueError("Round1 手牌详情映射观察必须与 --single-step 一起使用")
        override = _deep_merge(
            override,
            {
                "ProduceHIFRound1ActionFlag": {
                    "action": {
                        "param": {
                            "custom_action_param": {
                                "preset_id": "rinami_good_condition_safe",
                                "round": "round1",
                                "execution_mode": "observe_and_stop",
                                "round_probe": "hand_details_map_observe",
                                "round_probe_execution_mode": "single_step",
                            }
                        }
                    }
                },
                "ProduceEntryHIF": {"next": ["[JumpBack]ProduceHIFRound1Flag", "ProduceHIFUnknownStop"]},
            },
        )
    if args.round1_hand_detail_map_deck_observe:
        if not args.single_step:
            raise ValueError("Round1 手牌详情映射加牌库观察必须与 --single-step 一起使用")
        override = _deep_merge(
            override,
            {
                "ProduceHIFRound1ActionFlag": {
                    "action": {
                        "param": {
                            "custom_action_param": {
                                "preset_id": "rinami_good_condition_safe",
                                "round": "round1",
                                "execution_mode": "observe_and_stop",
                                "round_probe": "hand_details_map_deck_observe",
                                "round_probe_execution_mode": "single_step",
                            }
                        }
                    }
                },
                "ProduceEntryHIF": {"next": ["[JumpBack]ProduceHIFRound1Flag", "ProduceHIFUnknownStop"]},
            },
        )
    if args.round1_hand_detail_map_deck_observe_from_selected:
        if not args.single_step:
            raise ValueError("Round1 已选手牌详情映射加牌库观察必须与 --single-step 一起使用")
        override = _deep_merge(
            override,
            {
                "ProduceHIFRound1ActionFlag": {
                    "action": {
                        "param": {
                            "custom_action_param": {
                                "preset_id": "rinami_good_condition_safe",
                                "round": "round1",
                                "execution_mode": "observe_and_stop",
                                "round_probe": "hand_details_map_deck_observe_from_selected",
                                "round_probe_execution_mode": "single_step",
                            }
                        }
                    }
                },
                "ProduceEntryHIF": {"next": ["[JumpBack]ProduceHIFRound1Flag", "ProduceHIFUnknownStop"]},
            },
        )
    if args.round1_hand_detail_map_deck_select_one_from_selected:
        if not args.single_step:
            raise ValueError("Round1 已选手牌详情映射后选择一张卡必须与 --single-step 一起使用")
        override = _deep_merge(
            override,
            {
                "ProduceHIFRound1ActionFlag": {
                    "action": {
                        "param": {
                            "custom_action_param": {
                                "preset_id": "rinami_good_condition_safe",
                                "round": "round1",
                                "execution_mode": "single_step",
                                "round_probe": "hand_details_map_deck_select_one_from_selected",
                                "round_probe_execution_mode": "single_step",
                            }
                        }
                    }
                },
                "ProduceEntryHIF": {"next": ["[JumpBack]ProduceHIFRound1Flag", "ProduceHIFUnknownStop"]},
            },
        )
    if args.round1_hand_detail_map_deck_play_one:
        if not args.single_step:
            raise ValueError("Round1 手牌详情映射加牌库单步出牌必须与 --single-step 一起使用")
        override = _deep_merge(
            override,
            {
                "ProduceHIFRound1ActionFlag": {
                    "action": {
                        "param": {
                            "custom_action_param": {
                                "preset_id": "rinami_good_condition_safe",
                                "round": "round1",
                                "execution_mode": "single_step",
                                "round_probe": "hand_details_map_deck_play_one",
                                "round_probe_execution_mode": "single_step",
                            }
                        }
                    }
                },
                "ProduceEntryHIF": {"next": ["[JumpBack]ProduceHIFRound1Flag", "ProduceHIFUnknownStop"]},
            },
        )
    if args.round1_hand_detail_map_deck_select_presence:
        if not args.single_step:
            raise ValueError("Round1 存在感首次选择必须与 --single-step 一起使用")
        override = _deep_merge(
            override,
            {
                "ProduceHIFRound1ActionFlag": {
                    "action": {
                        "param": {
                            "custom_action_param": {
                                "preset_id": "rinami_good_condition_safe",
                                "round": "round1",
                                "execution_mode": "single_step",
                                "round_probe": "hand_details_map_deck_select_explicit",
                                "round_probe_execution_mode": "single_step",
                                "explicit_card_name": "存在感",
                            }
                        }
                    }
                },
                "ProduceEntryHIF": {"next": ["[JumpBack]ProduceHIFRound1Flag", "ProduceHIFUnknownStop"]},
            },
        )
    if args.round1_selected_card_detail_probe:
        if not args.single_step:
            raise ValueError("Round1 当前已选卡详情探针必须与 --single-step 一起使用")
        override = _deep_merge(
            override,
            {
                "ProduceHIFRound1ActionFlag": {
                    "action": {
                        "param": {
                            "custom_action_param": {
                                "preset_id": "rinami_good_condition_safe",
                                "round": "round1",
                                "execution_mode": "observe_and_stop",
                                "round_probe": "selected_hand_detail_read_only",
                            }
                        }
                    }
                },
                "ProduceEntryHIF": {"next": ["[JumpBack]ProduceHIFRound1Flag", "ProduceHIFUnknownStop"]},
            },
        )
    if args.round1_turn_roi_probe:
        if not args.single_step:
            raise ValueError("Round1 回合 ROI 探针必须与 --single-step 一起使用")
        override = _deep_merge(
            override,
            {
                "ProduceHIFRound1ActionFlag": {
                    "action": {
                        "param": {
                            "custom_action_param": {
                                "preset_id": "rinami_good_condition_safe",
                                "round": "round1",
                                "execution_mode": "observe_and_stop",
                                "round_probe": "turn_roi_candidates",
                            }
                        }
                    }
                },
                "ProduceEntryHIF": {"next": ["[JumpBack]ProduceHIFRound1Flag", "ProduceHIFUnknownStop"]},
            },
        )
    if args.round1_counter_roi_probe:
        if not args.single_step:
            raise ValueError("Round1 计数器 ROI 探针必须与 --single-step 一起使用")
        override = _deep_merge(
            override,
            {
                "ProduceHIFRound1ActionFlag": {
                    "action": {
                        "param": {
                            "custom_action_param": {
                                "preset_id": "rinami_good_condition_safe",
                                "round": "round1",
                                "execution_mode": "observe_and_stop",
                                "round_probe": "counter_roi_candidates",
                            }
                        }
                    }
                },
                "ProduceEntryHIF": {"next": ["[JumpBack]ProduceHIFRound1Flag", "ProduceHIFUnknownStop"]},
            },
        )
    if args.round1_status_detail_slot is not None:
        if not args.single_step:
            raise ValueError("Round1 状态详情探针必须与 --single-step 一起使用")
        override = _deep_merge(
            override,
            {
                "ProduceHIFRound1ActionFlag": {
                    "action": {
                        "param": {
                            "custom_action_param": {
                                "preset_id": "rinami_good_condition_safe",
                                "round": "round1",
                                "execution_mode": "observe_and_stop",
                                "round_probe": "status_detail",
                                "round_probe_execution_mode": "single_step",
                                "status_slot": args.round1_status_detail_slot,
                            }
                        }
                    }
                },
                "ProduceEntryHIF": {"next": ["[JumpBack]ProduceHIFRound1Flag", "ProduceHIFUnknownStop"]},
            },
        )
    if args.round1_status_detail_close:
        if not args.single_step:
            raise ValueError("Round1 状态详情关闭必须与 --single-step 一起使用")
        override = _deep_merge(
            override,
            {
                "ProduceHIFRound1ActionFlag": {
                    "action": {
                        "param": {
                            "custom_action_param": {
                                "preset_id": "rinami_good_condition_safe",
                                "round": "round1",
                                "execution_mode": "observe_and_stop",
                                "round_probe": "status_detail_close",
                            }
                        }
                    }
                },
                "ProduceEntryHIF": {"next": ["ProduceHIFRound1ActionFlag", "ProduceHIFUnknownStop"]},
            },
        )
    if args.round1_status_effect_probe is not None:
        if not args.single_step:
            raise ValueError("Round1 指定状态效果探针必须与 --single-step 一起使用")
        override = _deep_merge(
            override,
            {
                "ProduceHIFRound1ActionFlag": {
                    "action": {
                        "param": {
                            "custom_action_param": {
                                "preset_id": "rinami_good_condition_safe",
                                "round": "round1",
                                "execution_mode": "observe_and_stop",
                                "round_probe": "named_status_effect",
                                "round_probe_execution_mode": "single_step",
                                "status_effect_name": args.round1_status_effect_probe,
                            }
                        }
                    }
                },
                "ProduceEntryHIF": {"next": ["[JumpBack]ProduceHIFRound1Flag", "ProduceHIFUnknownStop"]},
            },
        )
    if args.round1_details_observe:
        if not args.single_step:
            raise ValueError("Round1 详情观察必须与 --single-step 一起使用")
        override = _deep_merge(
            override,
            {
                "ProduceHIFRound1ActionFlag": {
                    "action": {
                        "param": {
                            "custom_action_param": {
                                "preset_id": "rinami_good_condition_safe",
                                "round": "round1",
                                "execution_mode": "observe_and_stop",
                                "round_probe": "details_metrics",
                                "round_probe_execution_mode": "single_step",
                            }
                        }
                    }
                },
                "ProduceEntryHIF": {"next": ["[JumpBack]ProduceHIFRound1Flag", "ProduceHIFUnknownStop"]},
            },
        )
    if args.round1_state_observe:
        if not args.single_step:
            raise ValueError("Round1 状态观察必须与 --single-step 一起使用")
        override = _deep_merge(
            override,
            {
                "ProduceHIFRound1ActionFlag": {
                    "action": {
                        "param": {
                            "custom_action_param": {
                                "preset_id": "rinami_good_condition_safe",
                                "round": "round1",
                                "execution_mode": "observe_and_stop",
                            }
                        }
                    }
                },
                "ProduceEntryHIF": {"next": ["[JumpBack]ProduceHIFRound1Flag", "ProduceHIFUnknownStop"]},
            },
        )
    if args.round1_deck_probe or args.round1_play_one:
        if not args.single_step:
            raise ValueError("Round1 牌库探针或单张出牌必须与 --single-step 一起使用")
        override = _deep_merge(
            override,
            {
                "ProduceHIFRound1ActionFlag": {
                    "action": {
                        "param": {
                            "custom_action_param": {
                                "preset_id": "rinami_good_condition_safe",
                                "round": "round1",
                                "execution_mode": "single_step" if args.round1_play_one else "observe_and_stop",
                                "round_probe": "deck_count",
                                "round_probe_execution_mode": "single_step",
                            }
                        }
                    }
                },
                "ProduceEntryHIF": {
                    "next": ["[JumpBack]ProduceHIFRound1Flag", "ProduceHIFUnknownStop"]
                },
            },
        )
    if args.round1_confirm_selected:
        if not args.single_step:
            raise ValueError("Round1 已选卡确认必须与 --single-step 一起使用")
        confirm_selected_name = args.round1_confirm_selected_name or "至高のエンタメ"
        override = _deep_merge(
            override,
            {
                "ProduceHIFRound1ActionFlag": {
                    "action": {
                        "param": {
                            "custom_action_param": {
                                "preset_id": "rinami_good_condition_safe",
                                "round": "round1",
                                "execution_mode": "single_step",
                                "confirm_selected_card": confirm_selected_name,
                            }
                        }
                    }
                },
                "ProduceEntryHIF": {"next": ["[JumpBack]ProduceHIFRound1Flag", "ProduceHIFUnknownStop"]},
            },
        )
    elif args.round1_confirm_selected_name:
        raise ValueError("指定已选卡名必须与 --round1-confirm-selected 一起使用")
    if args.round1_play_one_after_entertainment:
        if not args.single_step:
            raise ValueError("Round1 首牌后恢复出牌必须与 --single-step 一起使用")
        override = _deep_merge(
            override,
            {
                "ProduceHIFRound1ActionFlag": {
                    "action": {
                        "param": {
                            "custom_action_param": {
                                "preset_id": "rinami_good_condition_safe",
                                "round": "round1",
                                "execution_mode": "single_step",
                                "round_probe": "deck_count",
                                "round_probe_execution_mode": "single_step",
                                "reprise_recovery": "after_entertainment_turn8",
                            }
                        }
                    }
                },
                "ProduceEntryHIF": {"next": ["[JumpBack]ProduceHIFRound1Flag", "ProduceHIFUnknownStop"]},
            },
        )
    if args.select_change_target_name:
        if args.select_change_target_enumerate:
            raise ValueError("变卡目标枚举不能与指定目标同时启用")
        if not args.single_step:
            raise ValueError("指定变卡目标必须与 --single-step 一起使用")
        override = _deep_merge(
            override,
            {
                "ProduceHIFSelectChangeTargetFlag": {
                    "action": {
                        "param": {
                            "custom_action_param": {
                                "preset_id": "rinami_good_condition_safe",
                                "execution_mode": "single_step",
                                "select_change_target_names": [args.select_change_target_name],
                            }
                        }
                    }
                },
                "ProduceEntryHIF": {
                    "next": ["[JumpBack]ProduceHIFSelectChangeTargetFlag", "ProduceHIFUnknownStop"]
                },
            },
        )
    if args.select_change_target_enumerate:
        if not args.single_step:
            raise ValueError("变卡目标枚举必须与 --single-step 一起使用")
        override = _deep_merge(
            override,
            {
                "ProduceHIFSelectChangeTargetFlag": {
                    "recognition": "DirectHit",
                    "action": {
                        "param": {
                            "custom_action_param": {
                                "preset_id": "rinami_good_condition_safe",
                                "execution_mode": "single_step",
                                "select_change_target_probe": "enumerate_candidates",
                            }
                        }
                    },
                },
                "ProduceEntryHIF": {
                    "next": ["[JumpBack]ProduceHIFSelectChangeTargetFlag", "ProduceHIFUnknownStop"]
                },
            },
        )
    if args.drink_overflow_keep_black_vinegar:
        if not args.single_step:
            raise ValueError("饮料满仓恢复必须与 --single-step 一起使用")
        override = _deep_merge(
            override,
            {
                "ProduceHIFDrinkOverflowObserveFlag": {
                    "action": {
                        "param": {
                            "custom_action_param": {
                                "execution_mode": "single_step",
                                "drink_overflow_keep": "初星黒酢",
                            }
                        }
                    }
                }
            },
        )
    consult_probe = "enhance" if args.consult_observe_enhance else "delete" if args.consult_observe_delete else None
    if consult_probe:
        if not args.single_step:
            raise ValueError("咨询页面采样必须与 --single-step 一起使用")
        override = _deep_merge(
            override,
            {
                "ProduceHIFConsultFlag": {"action": {"param": {"custom_action_param": {"execution_mode": "single_step", "consult_probe": consult_probe}}}},
                "ProduceEntryHIF": {"next": ["[JumpBack]ProduceHIFConsultFlag", "ProduceHIFUnknownStop"]},
            },
        )
    source_probe_mode: bool | str | None = (
        "cancel_to_target"
        if args.source_deck_cancel_to_target
        else "full_grid"
        if args.source_deck_enumerate_all
        else "visible_grid_after_one_scroll"
        if args.source_deck_scroll_enumerate_visible
        else "visible_grid"
        if args.source_deck_enumerate_visible
        else "confirm_source_card"
        if args.source_deck_confirm_target
        else True
        if args.source_deck_probe
        else None
    )
    if source_probe_mode is not None:
        if not args.single_step:
            raise ValueError("源卡牌库探针必须与 --single-step 一起使用")
        source_override = source_deck_probe_override(source_probe_mode)
        if args.source_deck_confirm_target:
            params = source_override["ProduceHIFSelectChangeSourceFlag"]["action"]["param"]["custom_action_param"]
            if bool(args.source_deck_confirm_name) != bool(args.source_deck_confirm_slot):
                raise ValueError("指定源卡名和槽位必须同时提供")
            if args.source_deck_confirm_name:
                params.update(
                    {
                        "source_card_name": args.source_deck_confirm_name,
                        "source_card_slot": f"visible_slot_{args.source_deck_confirm_slot}",
                        "selected_target_name": args.select_change_target_name,
                        "explicit_target_authorized": bool(args.select_change_target_name),
                        "explicit_source_authorized": True,
                        "source_card_scroll_once": args.source_deck_confirm_scroll_once,
                    }
                )
            else:
                params["source_card_name"] = "大胆不敵"
        override = _deep_merge(override, source_override)
        if args.source_deck_cancel_to_target:
            override = _deep_merge(
                override,
                {
                    "ProduceHIFSelectChangeSourceFlag": {"recognition": "DirectHit"},
                    "ProduceEntryHIF": {
                        "next": ["[JumpBack]ProduceHIFSelectChangeSourceFlag", "ProduceHIFUnknownStop"]
                    },
                },
            )
        elif args.select_change_target_name and not args.source_deck_confirm_target:
            override = _deep_merge(
                override,
                {
                    "ProduceHIFSelectChangeTargetFlag": {
                        "next": ["ProduceHIFSelectChangeSourceFlag", "ProduceHIFUnknownStop"]
                    },
                    "ProduceEntryHIF": {
                        "next": [
                            "[JumpBack]ProduceHIFSelectChangeTargetFlag",
                            "ProduceHIFUnknownStop",
                        ]
                    }
                },
            )
        elif args.source_deck_confirm_target:
            override = _deep_merge(
                override,
                {
                    "ProduceEntryHIF": {
                        "next": ["[JumpBack]ProduceHIFSelectChangeSourceFlag", "ProduceHIFUnknownStop"]
                    }
                },
            )
    elif args.source_deck_confirm_name or args.source_deck_confirm_slot:
        raise ValueError("指定源卡名和槽位必须与 --source-deck-confirm-target 一起使用")
    elif args.source_deck_confirm_scroll_once:
        raise ValueError("源卡确认滚动必须与 --source-deck-confirm-target 一起使用")
    skill_reward_modes = sum(
        (args.skill_reward_enumerate, args.skill_reward_decide, args.skill_reward_receive, args.skill_reward_reveal_confirm)
    )
    if skill_reward_modes > 1:
        raise ValueError("技能卡枚举、纯决策与受限领取模式不能同时启用")
    if args.skill_reward_reveal_confirm:
        if not args.single_step:
            raise ValueError("技能卡展示层确认必须与 --single-step 一起使用")
        if not args.skill_reward_reveal_name:
            raise ValueError("技能卡展示层确认必须提供 --skill-reward-reveal-name")
        if args.skill_reward_initial_slot:
            raise ValueError("--skill-reward-initial-slot 不能与技能卡展示层确认一起使用")
        override = _deep_merge(override, skill_reward_reveal_override(args.skill_reward_reveal_name))
    elif args.skill_reward_receive:
        if not args.single_step:
            raise ValueError("技能卡受限领取必须与 --single-step 一起使用")
        override = _deep_merge(
            override,
            skill_reward_receive_override(args.skill_reward_initial_slot, isolate_root=not args.hif_from_home),
        )
    else:
        skill_reward_probe = "decide_candidates" if args.skill_reward_decide else "enumerate_candidates" if args.skill_reward_enumerate else None
        if skill_reward_probe is not None:
            if not args.single_step:
                raise ValueError("技能卡候选枚举或纯决策必须与 --single-step 一起使用")
            override = _deep_merge(
                override,
                skill_reward_probe_override(skill_reward_probe, args.skill_reward_initial_slot, isolate_root=not args.hif_from_home),
            )
        elif args.skill_reward_initial_slot:
            raise ValueError("--skill-reward-initial-slot 必须与技能卡枚举、纯决策或受限领取一起使用")
    if args.skill_reward_reveal_name and not args.skill_reward_reveal_confirm:
        raise ValueError("--skill-reward-reveal-name 必须与 --skill-reward-reveal-confirm 一起使用")
    return override or None


def _deep_merge(base: dict[str, Any], addition: dict[str, Any]) -> dict[str, Any]:
    """按 Maa Pipeline 覆盖语义递归合并，避免同一节点的识别和参数相互丢失。"""

    merged = copy.deepcopy(base)
    for key, value in addition.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _save_frame(controller, path: Path) -> dict[str, Any]:
    image = controller.post_screencap().wait().get()
    validation = validate_hif_frame(image)
    save_hif_image(image, path)
    return {"path": str(path), "size": list(get_image_size(image) or ()), "hif_frame_valid": validation.ok, "reason": validation.reason}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.adb_path.is_file():
        raise FileNotFoundError(f"ADB 不存在: {args.adb_path}")
    run_id = args.run_id or datetime.now().strftime("%Y%m%dT%H%M%S")
    evidence_dir = ROOT / "debug" / "hif-live" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)

    from maa.tasker import Tasker
    from maa.resource import Resource
    from maa.controller import AdbController

    controller = AdbController(adb_path=args.adb_path, address=args.adb)
    if not controller.post_connection().wait().succeeded:
        raise RuntimeError(f"ADB 控制器连接失败: {args.adb}")
    task_entry = "Produce" if args.hif_from_home and args.task == "ProduceEntryHIF" else args.task
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "task": task_entry,
        "single_step": args.single_step,
        "round1_deck_probe": args.round1_deck_probe,
        "round1_hand_detail_probe": args.round1_hand_detail_probe,
        "round1_hand_detail_probe_from_selected": args.round1_hand_detail_probe_from_selected,
        "round1_hand_detail_map_observe": args.round1_hand_detail_map_observe,
        "round1_hand_detail_map_deck_observe": args.round1_hand_detail_map_deck_observe,
        "round1_hand_detail_map_deck_observe_from_selected": args.round1_hand_detail_map_deck_observe_from_selected,
        "round1_hand_detail_map_deck_select_one_from_selected": args.round1_hand_detail_map_deck_select_one_from_selected,
        "round1_hand_detail_map_deck_play_one": args.round1_hand_detail_map_deck_play_one,
        "round1_hand_detail_map_deck_select_presence": args.round1_hand_detail_map_deck_select_presence,
        "round1_selected_card_detail_probe": args.round1_selected_card_detail_probe,
        "round1_turn_roi_probe": args.round1_turn_roi_probe,
        "round1_counter_roi_probe": args.round1_counter_roi_probe,
        "round1_status_detail_slot": args.round1_status_detail_slot,
        "round1_status_detail_close": args.round1_status_detail_close,
        "round1_status_effect_probe": args.round1_status_effect_probe,
        "round1_state_observe": args.round1_state_observe,
        "round1_play_one": args.round1_play_one,
        "round1_confirm_selected": args.round1_confirm_selected,
        "round1_confirm_selected_name": args.round1_confirm_selected_name,
        "round1_play_one_after_entertainment": args.round1_play_one_after_entertainment,
        "source_deck_probe": args.source_deck_probe,
        "source_deck_enumerate_visible": args.source_deck_enumerate_visible,
        "source_deck_scroll_enumerate_visible": args.source_deck_scroll_enumerate_visible,
        "source_deck_enumerate_all": args.source_deck_enumerate_all,
        "source_deck_confirm_target": args.source_deck_confirm_target,
        "source_deck_cancel_to_target": args.source_deck_cancel_to_target,
        "select_change_target_enumerate": args.select_change_target_enumerate,
        "skill_reward_enumerate": args.skill_reward_enumerate,
        "skill_reward_decide": args.skill_reward_decide,
        "skill_reward_receive": args.skill_reward_receive,
        "skill_reward_reveal_confirm": args.skill_reward_reveal_confirm,
        "skill_reward_reveal_name": args.skill_reward_reveal_name,
        "drink_overflow_keep_black_vinegar": args.drink_overflow_keep_black_vinegar,
        "skill_reward_initial_slot": args.skill_reward_initial_slot,
        "hif_from_home": args.hif_from_home,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "before": _save_frame(controller, evidence_dir / "before.png"),
    }

    resource = Resource()
    if not resource.post_bundle(ROOT / "assets" / "resource" / "base").wait().succeeded:
        raise RuntimeError("HIF 资源加载失败")
    for name, action_type in load_custom_actions().items():
        if not resource.register_custom_action(name, action_type()):
            raise RuntimeError(f"注册自定义 Action 失败: {name}")
    for name, recognition_type in load_custom_recognitions().items():
        if not resource.register_custom_recognition(name, recognition_type()):
            raise RuntimeError(f"注册自定义 Recognition 失败: {name}")

    tasker = Tasker()
    tasker.bind(resource, controller)
    tasker.set_log_dir(evidence_dir)
    tasker.set_recording(True)
    tasker.set_save_on_error(True)
    job = tasker.post_task(task_entry, pipeline_override=runtime_override(args))
    deadline = time.monotonic() + args.seconds
    while not job.done and time.monotonic() < deadline:
        time.sleep(0.2)
    if not job.done:
        tasker.post_stop().wait()
        manifest["result"] = "timeout_stopped"
    else:
        manifest["result"] = "completed"
        manifest["succeeded"] = job.succeeded
        manifest["failed"] = job.failed
    manifest["finished_at"] = datetime.now().isoformat(timespec="seconds")
    manifest["after"] = _save_frame(controller, evidence_dir / "after.png")
    (evidence_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest["result"] == "completed" and not manifest.get("failed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
