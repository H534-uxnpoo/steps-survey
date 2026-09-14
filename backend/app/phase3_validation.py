"""Privacy-preserving batch validation for the Phase 3 checkbox reader."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .image_processing import DocumentDetectionError, ScanError, scan_front_with_diagnostics
from .models import ScanFields
from .template import load_template_config

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
FIELD_NAMES = ("performance", "age")


class LabelFormatError(ValueError):
    """Private expected-answer labels are missing or structurally invalid."""


def private_image_paths(image_directory: Path) -> list[Path]:
    """Return supported images without exposing their filenames in output."""
    return sorted(
        path
        for path in image_directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def _valid_choices() -> dict[str, set[str]]:
    config = load_template_config()
    return {
        field: {option["value"] for option in config[field]["options"]}
        for field in FIELD_NAMES
    }


def load_private_labels(
    label_path: Path,
) -> dict[str, dict[str, str | None]] | None:
    """Load filename-keyed labels from an ignored local file, if it exists."""
    if not label_path.exists():
        return None
    try:
        label_data = json.loads(label_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LabelFormatError("正解ラベルファイルを読み込めません。") from error

    if not isinstance(label_data, dict) or "samples" in label_data:
        raise LabelFormatError("正解ラベルは画像ファイル名をキーにしたJSONオブジェクトにしてください。")

    valid_choices = _valid_choices()
    normalized: dict[str, dict[str, str | None]] = {}
    for filename, sample in label_data.items():
        if not isinstance(filename, str) or not filename:
            raise LabelFormatError("正解ラベルの画像ファイル名が不正です。")
        if not isinstance(sample, dict):
            raise LabelFormatError("正解ラベルの形式が不正です。")
        expected: dict[str, str | None] = {}
        for field in FIELD_NAMES:
            value = sample.get(field)
            if value is not None and (not isinstance(value, str) or value not in valid_choices[field]):
                raise LabelFormatError("正解ラベルに未定義の選択肢があります。")
            expected[field] = value
        normalized[filename] = expected
    return normalized


def _empty_field_summary() -> dict[str, int | float | None]:
    return {"labeled": 0, "correct": 0, "needsReview": 0, "accuracy": None}


def _finish_field_summary(summary: dict[str, int | float | None]) -> None:
    labeled = int(summary["labeled"])
    summary["accuracy"] = round(int(summary["correct"]) / labeled, 4) if labeled else None


def build_validation_report(
    image_paths: Sequence[Path],
    expected_labels: Mapping[str, dict[str, str | None]] | None,
    scanner: Callable[
        [bytes], ScanFields | tuple[ScanFields, dict[str, float | int | str | bool]]
    ] = scan_front_with_diagnostics,
) -> dict[str, Any]:
    """Scan a batch and return only opaque IDs and non-personal aggregates."""
    summaries = {field: _empty_field_summary() for field in FIELD_NAMES}
    correction_success = 0
    cases: list[dict[str, Any]] = []

    for index, image_path in enumerate(image_paths, start=1):
        expected = expected_labels.get(image_path.name) if expected_labels is not None else None
        case: dict[str, Any] = {
            "sample": f"sample-{index:03d}",
            "correction": "failure",
            "needsReview": True,
            "fields": {},
        }
        try:
            scan_result = scanner(image_path.read_bytes())
        except DocumentDetectionError as error:
            fields = None
            case["diagnosticCode"] = error.code
            case["diagnostics"] = error.diagnostics
        except (OSError, ScanError):
            fields = None
        else:
            if isinstance(scan_result, tuple):
                fields, diagnostics = scan_result
                case["diagnostics"] = diagnostics
            else:
                fields = scan_result
            correction_success += 1
            case["correction"] = "success"
            case["needsReview"] = fields.performance.needsReview or fields.age.needsReview

        for field in FIELD_NAMES:
            field_case: dict[str, Any] = {"needsReview": True, "outcome": "not_evaluated"}
            summary = summaries[field]
            expected_value = expected[field] if expected is not None else None
            if expected_value is not None:
                summary["labeled"] = int(summary["labeled"]) + 1

            if fields is not None:
                result = getattr(fields, field)
                field_case["needsReview"] = result.needsReview
                if expected_value is None:
                    field_case["outcome"] = "unlabeled"
                elif result.value == expected_value:
                    summary["correct"] = int(summary["correct"]) + 1
                    field_case["outcome"] = "correct"
                else:
                    field_case["outcome"] = "incorrect"

            if field_case["needsReview"]:
                summary["needsReview"] = int(summary["needsReview"]) + 1
            case["fields"][field] = field_case
        cases.append(case)

    for summary in summaries.values():
        _finish_field_summary(summary)
    image_filenames = {path.name for path in image_paths}
    orphaned_labels = (
        len(set(expected_labels) - image_filenames) if expected_labels is not None else 0
    )
    missing_labels = sum(
        1 for path in image_paths if expected_labels is None or path.name not in expected_labels
    )
    return {
        "imageCount": len(image_paths),
        "labelsLoaded": expected_labels is not None,
        "labelCoverage": {
            "labeledImages": len(image_paths) - missing_labels,
            "missingLabels": missing_labels,
            "orphanedLabels": orphaned_labels,
        },
        "correction": {
            "success": correction_success,
            "failure": len(image_paths) - correction_success,
        },
        "fields": summaries,
        "cases": cases,
    }


def validate_private_directory(image_directory: Path, label_path: Path) -> dict[str, Any]:
    image_paths = private_image_paths(image_directory)
    labels = load_private_labels(label_path)
    return build_validation_report(image_paths, labels)
