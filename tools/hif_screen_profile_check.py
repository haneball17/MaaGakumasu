"""离线校验 HIF 已审阅页面配置与 Pipeline 安全入口。"""

from __future__ import annotations

import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.hif.ui_map import load_hif_ui_map
from agent.hif.screen_profiles import load_hif_screen_profiles


def main() -> int:
    profiles = load_hif_screen_profiles()
    ui_map = load_hif_ui_map()
    issues: list[str] = []
    if len(profiles.review_sections) != 34:
        issues.append(f"review_section_count:{len(profiles.review_sections)}")
    for profile in profiles.profiles.values():
        for button_id, button in profile.buttons.items():
            if ui_map.button_roi(profile.screen_id, button_id) != button.roi:
                issues.append(f"button_mapping_mismatch:{profile.screen_id}.{button_id}")
    print(
        json.dumps(
            {
                "ok": not issues,
                "profile_id": profiles.profile_id,
                "review_section_count": len(profiles.review_sections),
                "screen_count": len(profiles.profiles),
                "button_count": len(ui_map.buttons),
                "issues": issues,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
