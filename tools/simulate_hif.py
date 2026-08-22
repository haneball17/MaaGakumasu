import sys
import json
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.hif import (
    replay_hif_case,
    load_decision_data,
    simulate_hif_route,
    simulate_hif_rewards,
    build_sample_hif_case,
    build_hif_evaluation_report,
    build_default_produce_profile,
    build_default_scenario_config,
    build_default_hif_evaluation_config,
)
from agent.hif.simulator import load_produce_profile, load_scenario_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HIF 决策模块离线 CLI 模拟器")
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--decision-data", default=str(Path("assets/data/produce_decision_data.json")))
    common.add_argument("--scenario-file")
    common.add_argument("--profile-file")
    common.add_argument("--output", choices=["json", "text"], default="text")

    subparsers.add_parser("simulate_hif_route", parents=[common])

    reward = subparsers.add_parser("simulate_hif_rewards", parents=[common])
    reward.add_argument("--reward-kind", choices=["skill_acquire", "skill_upgrade", "skill_delete", "p_item"], default="skill_acquire")
    reward.add_argument("--limit", type=int, default=5)

    subparsers.add_parser("report_hif_evaluation", parents=[common])

    replay = subparsers.add_parser("replay_hif_case", parents=[common])
    replay.add_argument("--case-file", required=True)

    return parser


def _load_runtime(args) -> tuple:
    data = load_decision_data(args.decision_data)
    scenario = load_scenario_config(args.scenario_file) if args.scenario_file else build_default_scenario_config()
    profile = load_produce_profile(args.profile_file) if args.profile_file else build_default_produce_profile(data)
    return data, scenario, profile


def _print_text_route(result: dict) -> None:
    print(f"Scenario: {result['scenario']['scenario_name']}")
    print(f"Profile: {result['profile']['card_name_jp']} / {result['profile']['build']}")
    print("=" * 72)
    for step in result["steps"]:
        decision = step["decision"]
        selected = decision["selected_action"]["name"]
        reasons = " / ".join(decision["top_reasons"])
        print(f"{step['label']} [{step['phase']}] -> {selected}")
        print(f"  reasons: {reasons}")
        print(f"  confidence: {decision['confidence']}")
    print("=" * 72)
    snapshot = result["selection_snapshot"]
    memory = result["selection_memory_profile"]
    print("SelectionSnapshot:")
    print(
        f"  star={snapshot['star_value']} deck={snapshot['deck_size']} "
        f"trial={snapshot['trial_readiness']} memory={snapshot['memory_quality']} deck_quality={snapshot['deck_quality']}"
    )
    print("SelectionMemoryProfile:")
    print(
        f"  star={memory['star_value']} deck={memory['deck_size']} "
        f"memory={memory['memory_quality']} pending_support={memory['pending_support_events']}"
    )


def _print_text_rewards(result: dict) -> None:
    selected = result["selected_option"]
    print(f"Reward kind: {result['reward_kind']}")
    if selected:
        print(f"Selected: {selected['name']}  score={selected['score']}  reasons={' / '.join(selected['top_reasons'])}")
    print("-" * 72)
    for row in result["ranked_options"]:
        print(f"{row['name']}: score={row['score']} tags={','.join(row['tags']) or '-'}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    data, scenario, profile = _load_runtime(args)

    if args.command == "simulate_hif_route":
        result = simulate_hif_route(scenario, profile, build_sample_hif_case(data, profile))
        if args.output == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            _print_text_route(result)
        return 0

    if args.command == "simulate_hif_rewards":
        result = simulate_hif_rewards(profile, data, args.reward_kind, limit=args.limit)
        if args.output == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            _print_text_rewards(result)
        return 0

    if args.command == "report_hif_evaluation":
        route_result = simulate_hif_route(scenario, profile, build_sample_hif_case(data, profile))
        report = build_hif_evaluation_report(build_default_hif_evaluation_config(), route_result, scenario)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.command == "replay_hif_case":
        result = replay_hif_case(scenario, profile, args.case_file)
        if args.output == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            _print_text_route(result)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
