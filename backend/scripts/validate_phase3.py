"""Run Phase 3 batch validation without printing image names or answer values."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.phase3_validation import LabelFormatError, validate_private_directory


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 3 checkbox batch validation")
    parser.add_argument("--image-dir", type=Path, default=Path("test-data/private"))
    parser.add_argument(
        "--labels",
        type=Path,
        default=Path("test-data/private/phase3_labels.json"),
        help="Ignored local JSON file; output never includes its values.",
    )
    arguments = parser.parse_args()
    try:
        report = validate_private_directory(arguments.image_dir, arguments.labels)
    except (LabelFormatError, OSError):
        print(json.dumps({"error": "validation_setup_failed"}))
        return 2
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
