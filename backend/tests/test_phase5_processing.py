import cv2
import numpy as np

from app.image_processing import (
    CheckboxMeasurement,
    _validate_email,
    _validate_postal_code,
    result_for_multiple_select,
    result_for_single_select,
    scan_front_with_ocr,
)
from app.models import FieldResult
from app.ocr import OcrResult
from app.template import load_template_config, load_template_image


class RoiFakeOcrClient:
    def __init__(self, responses: list[OcrResult]) -> None:
        self.responses = iter(responses)
        self.request_shapes: list[tuple[int, int]] = []

    def recognize(self, image_bytes: bytes) -> OcrResult:
        image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        shape = image.shape[:2]
        self.request_shapes.append(shape)
        return next(self.responses)


def _mark(image, option: dict) -> None:
    x, y, width, height = option["box"]
    cv2.line(image, (x + 5, y + 5), (x + width - 6, y + height - 6), (0, 0, 0), 2)
    cv2.line(image, (x + width - 6, y + 5), (x + 5, y + height - 6), (0, 0, 0), 2)


def test_phase_five_ocr_is_per_roi_and_structures_selected_details():
    config = load_template_config()
    image = load_template_image().copy()
    _mark(image, config["trigger"]["options"][2])
    _mark(image, config["trigger"]["options"][7])
    _mark(image, config["media"]["options"][8])
    _mark(image, config["reservation"]["options"][2])
    success, encoded = cv2.imencode(".png", image)
    assert success

    ocr_values = {
        "message": "DUMMY MESSAGE",
        "name": "DUMMY NAME",
        "mailing_name": "DUMMY MAILING NAME",
        "postal_code": "〒123-4567",
        "address": "DUMMY ADDRESS",
        "email": "dummy@example.test",
        "trigger_related_name": "DUMMY PERSON",
        "trigger_other": "DUMMY TRIGGER",
        "media_other": "DUMMY MEDIA",
        "reservation_other": "DUMMY RESERVATION",
    }
    requested_fields = [
        "message", "name", "mailing_name", "postal_code", "address", "email",
        "trigger_related_name", "trigger_other", "media_other", "reservation_other",
    ]
    client = RoiFakeOcrClient([OcrResult(ocr_values[key], 0.99) for key in requested_fields])

    fields = scan_front_with_ocr(encoded.tobytes(), client)

    assert fields.name.value == "DUMMY NAME"
    assert fields.mailingName.value == "DUMMY MAILING NAME"
    assert fields.postalCode.value == "123-4567"
    assert fields.postalCode.needsReview is False
    assert fields.address.value == "DUMMY ADDRESS"
    assert fields.email.value == "dummy@example.test"
    assert fields.trigger.value == "関係者の誘い（DUMMY PERSON）, その他（DUMMY TRIGGER）"
    assert fields.media.value == "その他（DUMMY MEDIA）"
    assert fields.reservation.value == "その他（DUMMY RESERVATION）"

    expected_shapes = [(config[key]["roi"][3], config[key]["roi"][2]) for key in requested_fields]
    assert client.request_shapes == expected_shapes
    assert all(shape != image.shape[:2] for shape in client.request_shapes)


def test_invalid_postal_code_and_email_are_not_corrected_and_require_review():
    invalid_postal = _validate_postal_code(
        FieldResult(value="12O-4567", confidence=0.99, needsReview=False, status="recognized")
    )
    invalid_email = _validate_email(
        FieldResult(value="dummy.example.test", confidence=0.99, needsReview=False, status="recognized")
    )

    assert invalid_postal.value == "12O-4567"
    assert invalid_postal.needsReview is True
    assert invalid_email.value == "dummy.example.test"
    assert invalid_email.needsReview is True


def test_phase_five_ocr_fallback_keeps_checkbox_results_and_marks_text_for_review():
    image = load_template_image()
    success, encoded = cv2.imencode(".png", image)
    assert success

    fields = scan_front_with_ocr(encoded.tobytes(), None)

    assert fields.performance.status in {"none", "selected", "uncertain"}
    assert all(
        getattr(fields, field_name).status == "unavailable"
        for field_name in ("message", "name", "mailingName", "postalCode", "address", "email")
    )


def test_checkbox_reader_keeps_weak_ink_out_of_confirmed_multi_select():
    checkbox_config = {
        "checked_ink_ratio": 0.02,
        "confirmed_ink_ratio": 0.06,
        "suppress_ambiguous_value": True,
    }
    readings = [
        CheckboxMeasurement("CONFIRMED", 0.30),
        CheckboxMeasurement("WEAK", 0.028),
        CheckboxMeasurement("EMPTY", 0),
    ]

    multiple = result_for_multiple_select(readings, checkbox_config)
    single = result_for_single_select(
        [CheckboxMeasurement("WEAK", 0.028), CheckboxMeasurement("EMPTY", 0)], checkbox_config
    )

    assert multiple.value == ""
    assert multiple.candidates == ["CONFIRMED"]
    assert multiple.needsReview is True
    assert multiple.status == "uncertain"
    assert single.value == ""
    assert single.status == "uncertain"
    assert single.needsReview is True


def test_checkbox_reader_rejects_frame_like_component_even_above_ratio():
    checkbox_config = {
        "checked_ink_ratio": 0.02,
        "confirmed_ink_ratio": 0.06,
        "minimum_confirmed_component_px": 3,
        "require_component_shape": True,
    }
    reading = CheckboxMeasurement("FRAME_LEAK", 0.30, 12, 1, 6)
    result = result_for_multiple_select([reading], checkbox_config)
    assert result.value == ""
    assert result.needsReview is True


def test_selected_option_remains_confirmed_when_only_its_detail_ocr_is_unavailable():
    config = load_template_config()
    image = load_template_image().copy()
    _mark(image, config["trigger"]["options"][2])
    success, encoded = cv2.imencode(".png", image)
    assert success

    fields = scan_front_with_ocr(encoded.tobytes(), None)

    assert fields.trigger.status == "selected"
    assert fields.trigger.needsReview is False
    assert fields.trigger.detailNeedsReview is True
