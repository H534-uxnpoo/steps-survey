import cv2
import numpy as np

from fastapi.testclient import TestClient

from app.main import app
from app.ocr import OcrResult
from app.template import load_template_config, load_template_image

client = TestClient(app)


class FakeMessageOcrClient:
    def __init__(self) -> None:
        self.request = b""

    def recognize(self, image_bytes: bytes) -> OcrResult:
        self.request = image_bytes
        return OcrResult(text="DUMMY MESSAGE", confidence=0.95)


class FakeBackOcrClient:
    def recognize(self, image_bytes: bytes) -> OcrResult:
        assert image_bytes
        return OcrResult(text="DUMMY BACK", confidence=0.95)


def test_scan_endpoint_returns_phase_five_fields(monkeypatch):
    fake_client = FakeMessageOcrClient()
    monkeypatch.setattr("app.main.get_message_ocr_client", lambda: fake_client)
    image = load_template_image().copy()
    config = load_template_config()
    option = config["performance"]["options"][0]
    x, y, width, height = option["box"]
    cv2.line(image, (x + 4, y + 4), (x + width - 5, y + height - 5), (0, 0, 0), 2)
    success, encoded = cv2.imencode(".png", image)
    assert success

    response = client.post(
        "/api/scan/front",
        files={"image": ("survey.png", encoded.tobytes(), "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body["fields"]) == {
        "performance", "age", "trigger", "media", "reservation", "message",
        "name", "mailingName", "postalCode", "address", "email",
    }
    assert body["fields"]["performance"]["value"] == "12日(土)12:30-"
    assert body["fields"]["message"] == {
        "value": "DUMMY MESSAGE",
        "confidence": 0.95,
        "needsReview": False,
        "detailNeedsReview": False,
        "candidates": [],
        "status": "recognized",
    }
    assert fake_client.request.startswith(b"\x89PNG\r\n\x1a\n")
    assert "scanId" in body


def test_scan_endpoint_rejects_non_image_uploads():
    response = client.post(
        "/api/scan/front",
        files={"image": ("invalid.txt", b"not an image", "text/plain")},
    )
    assert response.status_code == 415


def test_scan_endpoint_returns_recapture_guidance_for_unusable_document():
    image = np.full((100, 100, 3), 255, dtype=np.uint8)
    success, encoded = cv2.imencode(".png", image)
    assert success

    response = client.post(
        "/api/scan/front",
        files={"image": ("too-small.png", encoded.tobytes(), "image/png")},
    )

    assert response.status_code == 422
    assert "アンケート全体" in response.json()["detail"]


def test_back_scan_endpoint_uses_free_form_ocr_without_template_alignment(monkeypatch):
    monkeypatch.setattr("app.main.get_message_ocr_client", lambda: FakeBackOcrClient())
    image = np.zeros((40, 60, 3), dtype=np.uint8)
    success, encoded = cv2.imencode(".png", image)
    assert success
    response = client.post(
        "/api/scan/back",
        files={"image": ("back.png", encoded.tobytes(), "image/png")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["message"]["value"] == "DUMMY BACK"
    assert body["message"]["needsReview"] is False


def test_back_scan_without_ocr_returns_reviewable_result(monkeypatch):
    monkeypatch.setattr("app.main.get_message_ocr_client", lambda: None)
    image = np.zeros((40, 60, 3), dtype=np.uint8)
    success, encoded = cv2.imencode(".png", image)
    assert success
    response = client.post(
        "/api/scan/back",
        files={"image": ("back.png", encoded.tobytes(), "image/png")},
    )
    assert response.status_code == 200
    assert response.json()["message"]["status"] == "unavailable"
    assert response.json()["needsReview"] is True
