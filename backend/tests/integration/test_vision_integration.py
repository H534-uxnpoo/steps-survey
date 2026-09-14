"""Optional live Vision test. It is skipped unless the operator enables it."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.image_processing import correct_document, decode_image
from app.ocr import GoogleVisionMessageOcrClient, recognize_message
from app.template import load_template_config


pytestmark = pytest.mark.integration


def test_google_vision_message_crop_only():
    if os.environ.get("RUN_VISION_INTEGRATION") != "1":
        pytest.skip("set RUN_VISION_INTEGRATION=1 to allow a live Vision request")
    if os.environ.get("VISION_OCR_ENABLED", "").lower() != "true":
        pytest.skip("set VISION_OCR_ENABLED=true to enable backend OCR")

    private_directory = Path(__file__).resolve().parents[3] / "test-data" / "private"
    samples = [*private_directory.glob("*.jpg"), *private_directory.glob("*.jpeg"), *private_directory.glob("*.png")]
    if not samples:
        pytest.skip("no local private image is available")

    aligned = correct_document(decode_image(samples[0].read_bytes()))
    result = recognize_message(aligned, load_template_config(), GoogleVisionMessageOcrClient())

    # Do not assert or print OCR text; the live request sends only the ROI.
    assert result.status in {"recognized", "uncertain", "none"}
