"""统一数据目录的仓库路径。"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "assets" / "data"
CATALOG_ROOT = DATA_ROOT / "catalog"
SCHEMAS_ROOT = CATALOG_ROOT / "schemas"
MANIFESTS_ROOT = CATALOG_ROOT / "manifests"
ASSERTIONS_ROOT = CATALOG_ROOT / "assertions"
CANONICAL_ROOT = CATALOG_ROOT / "canonical"
OVERLAYS_ROOT = CATALOG_ROOT / "overlays"
FIXTURES_ROOT = CATALOG_ROOT / "fixtures"
REPORTS_ROOT = CATALOG_ROOT / "reports"
DECISIONS_ROOT = CATALOG_ROOT / "decisions"
CACHE_ROOT = PROJECT_ROOT / ".cache" / "gakumas-data"


def ensure_catalog_dirs() -> None:
    for path in (
        MANIFESTS_ROOT,
        ASSERTIONS_ROOT,
        CANONICAL_ROOT,
        OVERLAYS_ROOT,
        FIXTURES_ROOT,
        REPORTS_ROOT,
        DECISIONS_ROOT,
        CACHE_ROOT / "raw",
    ):
        path.mkdir(parents=True, exist_ok=True)
