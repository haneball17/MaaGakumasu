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
        "--source-deck-confirm-target",
        action="store_true",
        help="仅在 --single-step 下重选已实测的大胆不敵并提交チェンジ；必须通过结果文本后验",
    )
    parser.add_argument("--source-deck-confirm-name", help="经用户明确授权的源卡名；仅能与 --source-deck-confirm-target 一起使用")
    parser.add_argument(
        "--source-deck-confirm-slot",
        choices=("r1c1", "r1c2", "r1c3", "r1c4", "r2c1", "r2c2", "r2c3", "r2c4", "r3c1", "r3c2", "r3c3", "r3c4"),
        help="经实机枚举确认的源卡槽位；仅能与 --source-deck-confirm-target 一起使用",
    )
    parser.add_argument(
        "--select-change-target-name",
        help="单步实机中由用户明确指定的变卡目标；不修改默认预设优先级",
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
    if args.select_change_target_name:
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
                }
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
        "visible_grid_after_one_scroll"
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
                        "explicit_source_authorized": True,
                    }
                )
            else:
                params["source_card_name"] = "大胆不敵"
        override = _deep_merge(override, source_override)
    elif args.source_deck_confirm_name or args.source_deck_confirm_slot:
        raise ValueError("指定源卡名和槽位必须与 --source-deck-confirm-target 一起使用")
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
        "source_deck_probe": args.source_deck_probe,
        "source_deck_enumerate_visible": args.source_deck_enumerate_visible,
        "source_deck_scroll_enumerate_visible": args.source_deck_scroll_enumerate_visible,
        "source_deck_confirm_target": args.source_deck_confirm_target,
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
