"""Phase 4 message-field OCR, with no image persistence or content logging."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Protocol

import cv2
import numpy as np

from .models import FieldResult


class OcrError(RuntimeError):
    """A safe OCR error which never contains provider or recognised text."""


@dataclass(frozen=True)
class OcrResult:
    text: str
    confidence: float


class OcrClient(Protocol):
    def recognize(self, image_bytes: bytes) -> OcrResult: ...


# Kept as a compatibility alias for the Phase 4 integration point.
MessageOcrClient = OcrClient


class GoogleVisionMessageOcrClient:
    """Thin lazy Vision wrapper; authentication remains in the backend runtime."""

    def __init__(self) -> None:
        try:
            from google.cloud import vision
        except ImportError as error:
            raise OcrError("vision_client_unavailable") from error
        self._vision = vision
        try:
            self._client = vision.ImageAnnotatorClient()
        except Exception as error:
            raise OcrError("vision_client_initialization_failed") from error

    def recognize(self, image_bytes: bytes) -> OcrResult:
        try:
            response = self._client.document_text_detection(
                image=self._vision.Image(content=image_bytes)
            )
        except Exception as error:
            raise OcrError("vision_request_failed") from error

        if response.error.message:
            raise OcrError("vision_request_failed")

        # Return exactly what the service supplied.  Do not trim, normalize,
        # summarize, infer, or otherwise alter handwritten content.
        text = response.full_text_annotation.text or ""
        confidences: list[float] = []
        for page in response.full_text_annotation.pages:
            for block in page.blocks:
                for paragraph in block.paragraphs:
                    for word in paragraph.words:
                        confidences.append(float(word.confidence))
        confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return OcrResult(text=text, confidence=confidence)


def get_ocr_client() -> OcrClient | None:
    """Create a client only when OCR was explicitly enabled for this backend."""
    if os.environ.get("VISION_OCR_ENABLED", "").lower() != "true":
        return None
    try:
        return GoogleVisionMessageOcrClient()
    except OcrError:
        return None


def get_message_ocr_client() -> OcrClient | None:
    """Compatibility wrapper for callers added during Phase 4."""
    return get_ocr_client()


def recognize_back_image(image_bytes: bytes, client: OcrClient | None) -> FieldResult:
    """OCR a back-side image as free-form text, without template alignment."""
    if client is None:
        return FieldResult(confidence=0, needsReview=True, status="unavailable")
    try:
        result = client.recognize(image_bytes)
    except Exception:
        return FieldResult(confidence=0, needsReview=True, status="unavailable")
    if not result.text:
        return FieldResult(confidence=result.confidence, needsReview=True, status="none")
    if result.confidence < 0.8:
        return FieldResult(
            value=result.text,
            confidence=result.confidence,
            needsReview=True,
            status="uncertain",
        )
    return FieldResult(
        value=result.text,
        confidence=result.confidence,
        needsReview=False,
        status="recognized",
    )
def encode_field_crop(aligned_image: np.ndarray, field_config: dict) -> bytes:
    """Encode one configured ROI in memory; never encode the whole survey."""
    x, y, width, height = (int(value) for value in field_config["roi"])
    image_height, image_width = aligned_image.shape[:2]
    if (
        width <= 0
        or height <= 0
        or x < 0
        or y < 0
        or x + width > image_width
        or y + height > image_height
    ):
        raise OcrError("ocr_roi_invalid")
    crop = aligned_image[y : y + height, x : x + width]
    encoded, buffer = cv2.imencode(".png", crop)
    if not encoded:
        raise OcrError("ocr_crop_encoding_failed")
    return buffer.tobytes()


def encode_message_crop(aligned_image: np.ndarray, config: dict) -> bytes:
    """Phase 4 compatibility wrapper for the message ROI crop."""
    return encode_field_crop(aligned_image, config["message"])


def recognize_text_field(
    aligned_image: np.ndarray,
    field_config: dict,
    client: OcrClient | None,
) -> FieldResult:
    """Recognize one configured handwritten field without altering its text."""
    if client is None:
        return FieldResult(confidence=0, needsReview=True, status="unavailable")
    try:
        result = client.recognize(encode_field_crop(aligned_image, field_config))
    except Exception:
        return FieldResult(confidence=0, needsReview=True, status="unavailable")

    minimum_confidence = float(field_config["minimum_confidence"])
    if not result.text:
        # Empty provider output is intentionally distinct from an unavailable client.
        return FieldResult(confidence=result.confidence, needsReview=True, status="none")
    if result.confidence < minimum_confidence:
        return FieldResult(
            value=result.text,
            confidence=result.confidence,
            needsReview=True,
            status="uncertain",
        )
    return FieldResult(
        value=result.text,
        confidence=result.confidence,
        needsReview=False,
        status="recognized",
    )


def recognize_message(
    aligned_image: np.ndarray, config: dict, client: MessageOcrClient | None
) -> FieldResult:
    """OCR the message crop only; failures are explicitly reviewable."""
    return recognize_text_field(aligned_image, config["message"], client)
