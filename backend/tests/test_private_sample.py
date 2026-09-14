"""A local smoke test that never prints or persists private questionnaire data."""

from pathlib import Path

import pytest

from app.image_processing import scan_front


PRIVATE_DATA_DIRECTORY = Path(__file__).resolve().parents[2] / "test-data" / "private"


def test_private_sample_has_a_safe_phase_three_response():
    samples = list(PRIVATE_DATA_DIRECTORY.glob("*.jpg")) + list(
        PRIVATE_DATA_DIRECTORY.glob("*.jpeg")
    ) + list(PRIVATE_DATA_DIRECTORY.glob("*.png"))
    if not samples:
        pytest.skip("ローカルの非公開テスト画像がありません。")

    result = scan_front(samples[0].read_bytes())

    # This repository's local fixture is a completed questionnaire.  Keep the
    # assertion to statuses only so no answer or personal information is put in
    # test output or source control.
    assert result.performance.status in {"selected", "uncertain", "multiple", "none"}
    assert result.age.status in {"selected", "uncertain", "multiple", "none"}
