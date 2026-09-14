import json
from pathlib import Path

from app.image_processing import DocumentDetectionError
from app.models import FieldResult, ScanFields
from app.phase3_validation import build_validation_report, load_private_labels


def sample_fields() -> ScanFields:
    return ScanFields(
        performance=FieldResult(
            value="12日(土)12:30-",
            confidence=0.9,
            needsReview=False,
            candidates=["12日(土)12:30-"],
            status="selected",
        ),
        age=FieldResult(
            value="20代",
            confidence=0.9,
            needsReview=False,
            candidates=["20代"],
            status="selected",
        ),
        trigger=FieldResult(confidence=0, needsReview=True, status="unavailable"),
        media=FieldResult(confidence=0, needsReview=True, status="unavailable"),
        reservation=FieldResult(confidence=0, needsReview=True, status="unavailable"),
        message=FieldResult(confidence=0, needsReview=True, status="unavailable"),
        name=FieldResult(confidence=0, needsReview=True, status="unavailable"),
        mailingName=FieldResult(confidence=0, needsReview=True, status="unavailable"),
        postalCode=FieldResult(confidence=0, needsReview=True, status="unavailable"),
        address=FieldResult(confidence=0, needsReview=True, status="unavailable"),
        email=FieldResult(confidence=0, needsReview=True, status="unavailable"),
    )


TEST_IMAGE_PATH = Path(__file__)
FIXTURE_LABEL_PATH = Path(__file__).parent / "fixtures" / "phase3_labels.json"


def test_batch_report_uses_opaque_ids_and_aggregates_only():
    image_path = TEST_IMAGE_PATH
    labels = {image_path.name: {"performance": "12日(土)12:30-", "age": "20代"}}

    report = build_validation_report([image_path], labels, scanner=lambda _: sample_fields())
    serialized = json.dumps(report, ensure_ascii=False)

    assert report["correction"] == {"success": 1, "failure": 0}
    assert report["fields"]["performance"]["correct"] == 1
    assert report["fields"]["age"]["accuracy"] == 1.0
    assert report["cases"][0]["sample"] == "sample-001"
    assert "potentially-sensitive-name" not in serialized
    assert "12日(土)12:30-" not in serialized


def test_correction_failure_is_never_counted_as_a_confirmed_result():
    image_path = TEST_IMAGE_PATH
    labels = {image_path.name: {"performance": "12日(土)12:30-", "age": "20代"}}

    def failing_scanner(_: bytes) -> ScanFields:
        raise DocumentDetectionError("safe error")

    report = build_validation_report([image_path], labels, scanner=failing_scanner)

    assert report["correction"] == {"success": 0, "failure": 1}
    assert report["fields"]["performance"]["correct"] == 0
    assert report["fields"]["performance"]["needsReview"] == 1
    assert report["cases"][0]["needsReview"] is True


def test_private_labels_are_keyed_by_filename():
    assert load_private_labels(FIXTURE_LABEL_PATH) == {
        "sample-001.jpg": {"performance": "12日(土)12:30-", "age": "20代"}
    }


def test_missing_filename_label_is_reported_but_not_scored():
    report = build_validation_report(
        [TEST_IMAGE_PATH],
        {},
        scanner=lambda _: sample_fields(),
    )

    assert report["labelCoverage"]["missingLabels"] == 1
    assert report["fields"]["performance"]["labeled"] == 0
    assert report["cases"][0]["fields"]["performance"]["outcome"] == "unlabeled"
