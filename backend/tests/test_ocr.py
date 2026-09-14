import cv2
import numpy as np

from app.ocr import OcrError, OcrResult, encode_message_crop, recognize_message
from app.template import load_template_config, load_template_image


class CapturingOcrClient:
    def __init__(self, result: OcrResult) -> None:
        self.result = result
        self.request = b""

    def recognize(self, image_bytes: bytes) -> OcrResult:
        self.request = image_bytes
        return self.result


def test_message_ocr_receives_only_configured_crop():
    template = load_template_image()
    config = load_template_config()
    client = CapturingOcrClient(OcrResult(text="DUMMY MESSAGE", confidence=0.95))

    result = recognize_message(template, config, client)

    sent = cv2.imdecode(np.frombuffer(client.request, dtype=np.uint8), cv2.IMREAD_COLOR)
    _, _, expected_width, expected_height = config["message"]["roi"]
    assert sent.shape[:2] == (expected_height, expected_width)
    assert sent.shape[:2] != template.shape[:2]
    assert result.value == "DUMMY MESSAGE"
    assert result.status == "recognized"
    assert result.needsReview is False


def test_uncertain_or_empty_message_requires_review():
    template = load_template_image()
    config = load_template_config()

    low_confidence = recognize_message(
        template, config, CapturingOcrClient(OcrResult(text="DUMMY MESSAGE", confidence=0.2))
    )
    empty = recognize_message(template, config, CapturingOcrClient(OcrResult(text="", confidence=0)))

    assert low_confidence.value == "DUMMY MESSAGE"
    assert low_confidence.status == "uncertain"
    assert low_confidence.needsReview is True
    assert empty.status == "none"
    assert empty.needsReview is True


def test_unavailable_client_or_crop_error_requires_review():
    template = load_template_image()
    config = load_template_config()

    unavailable = recognize_message(template, config, None)
    invalid_config = {**config, "message": {"roi": [0, 0, 0, 1], "minimum_confidence": 0.8}}
    invalid = recognize_message(template, invalid_config, CapturingOcrClient(OcrResult("x", 1)))

    assert unavailable.status == "unavailable"
    assert unavailable.needsReview is True
    assert invalid.status == "unavailable"


def test_message_crop_rejects_out_of_bounds_roi():
    template = load_template_image()
    config = load_template_config()
    invalid_config = {**config, "message": {"roi": [0, 0, 9999, 1]}}

    try:
        encode_message_crop(template, invalid_config)
    except OcrError as error:
        assert str(error) == "ocr_roi_invalid"
    else:
        raise AssertionError("invalid ROI must not be cropped")
