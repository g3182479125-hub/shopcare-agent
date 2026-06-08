from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.services.data_importer import import_all


def resolve_existing(configured: str, fallback_pattern: str) -> Path:
    path = Path(configured)
    if path.exists():
        return path
    matches = list(Path("E:/agnet").glob(fallback_pattern))
    if not matches:
        raise FileNotFoundError(f"Cannot find data file for pattern: {fallback_pattern}")
    return matches[0]


def main() -> None:
    settings = get_settings()
    order_csv = resolve_existing(settings.order_csv_path, "*/order.csv")
    user_csv = resolve_existing(settings.user_csv_path, "*/user.csv")
    aftersales_csv = resolve_existing(settings.aftersales_csv_path, "aftersales_cases.csv")
    report = import_all(
        order_csv=order_csv,
        user_csv=user_csv,
        aftersales_csv=aftersales_csv,
        report_path=ROOT / "data" / "import_report.json",
    )
    print("Import completed:")
    print(f"- order_csv: {order_csv}")
    print(f"- user_csv: {user_csv}")
    print(f"- aftersales_csv: {aftersales_csv}")
    for key, value in report.items():
        print(f"- {key}: {value}")
    print(f"Database: {settings.db_path}")


if __name__ == "__main__":
    main()
