"""In-memory document correction and Phase 3 checkbox recognition."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

import cv2
import numpy as np

from .models import FieldResult, ScanFields
from .ocr import OcrClient, recognize_text_field
from .template import load_template_config, load_template_image


class ScanError(ValueError):
    """Safe-to-return processing errors that do not include image data."""


class UnsupportedImageError(ScanError):
    pass


class DocumentDetectionError(ScanError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "document_detection_failed",
        diagnostics: dict[str, float | int | str | bool] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.diagnostics = diagnostics or {}


@dataclass(frozen=True)
class CheckboxMeasurement:
    value: str
    ink_ratio: float


@dataclass(frozen=True)
class TemplateFeatureAttempt:
    aligned_image: np.ndarray | None
    code: str
    diagnostics: dict[str, float | int | str | bool]


def decode_image(image_bytes: bytes) -> np.ndarray:
    encoded = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise UnsupportedImageError("JPEGまたはPNG形式の画像を選択してください。")
    return image


def _order_corners(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    ordered = np.zeros((4, 2), dtype=np.float32)
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1).reshape(-1)
    ordered[0] = points[np.argmin(sums)]
    ordered[2] = points[np.argmax(sums)]
    ordered[1] = points[np.argmin(differences)]
    ordered[3] = points[np.argmax(differences)]
    return ordered


def _quad_aspect_ratio(corners: np.ndarray) -> float:
    top = np.linalg.norm(corners[1] - corners[0])
    left = np.linalg.norm(corners[3] - corners[0])
    if min(top, left) == 0:
        return 0.0
    return min(top, left) / max(top, left)


def find_document_corners(image: np.ndarray, config: dict) -> np.ndarray:
    """Return the largest plausible A-series paper quadrilateral."""
    height, width = image.shape[:2]
    image_area = height * width
    grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(grayscale, (5, 5), 0)
    edges = cv2.Canny(blurred, 45, 135)
    edges = cv2.morphologyEx(
        edges, cv2.MORPH_CLOSE, np.ones((5, 5), dtype=np.uint8), iterations=2
    )
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    expected_aspect = config["reference"]["width"] / config["reference"]["height"]
    tolerance = config["document_detection"]["aspect_ratio_tolerance"]
    minimum_area = config["document_detection"]["minimum_area_ratio"] * image_area
    candidates: list[tuple[float, np.ndarray]] = []

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < minimum_area:
            continue
        perimeter = cv2.arcLength(contour, True)
        approximation = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(approximation) != 4 or not cv2.isContourConvex(approximation):
            continue
        corners = _order_corners(approximation.reshape(4, 2))
        aspect = _quad_aspect_ratio(corners)
        if abs(aspect - expected_aspect) > tolerance:
            continue
        aspect_score = 1 - abs(aspect - expected_aspect) / tolerance
        candidates.append((area * aspect_score, corners))

    if candidates:
        return max(candidates, key=lambda candidate: candidate[0])[1]

    # A tightly cropped scan has no visible external edge.  Its full image is a
    # safe fallback only when it already has the questionnaire's aspect ratio.
    full_image_ratio = min(width, height) / max(width, height)
    if abs(full_image_ratio - expected_aspect) <= tolerance:
        return _order_corners(
            np.array(
                [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
                dtype=np.float32,
            )
        )

    raise DocumentDetectionError(
        "アンケート全体が画面に入るように、明るい場所で撮影してください。"
    )


def _orientation_score(image: np.ndarray, template: np.ndarray) -> float:
    scan_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    print_mask = template_gray < 180
    if not np.any(print_mask):
        return float("-inf")
    return float(np.mean(255 - scan_gray[print_mask]))


def _choose_upright_orientation(warped: np.ndarray, template: np.ndarray) -> np.ndarray:
    candidates: list[np.ndarray]
    if warped.shape[:2] == template.shape[:2]:
        candidates = [warped, cv2.rotate(warped, cv2.ROTATE_180)]
    else:
        candidates = [
            cv2.rotate(warped, cv2.ROTATE_90_CLOCKWISE),
            cv2.rotate(warped, cv2.ROTATE_90_COUNTERCLOCKWISE),
        ]
    return max(candidates, key=lambda candidate: _orientation_score(candidate, template))


def _align_with_template_features(
    image: np.ndarray, template: np.ndarray, config: dict
) -> TemplateFeatureAttempt:
    """Align a borderless scan using printed form features (not handwriting)."""
    if not hasattr(cv2, "SIFT_create"):
        return TemplateFeatureAttempt(None, "feature_unavailable", {})

    template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    detector = cv2.SIFT_create()
    template_keypoints, template_descriptors = detector.detectAndCompute(template_gray, None)
    image_keypoints, image_descriptors = detector.detectAndCompute(image_gray, None)
    if template_descriptors is None or image_descriptors is None:
        return TemplateFeatureAttempt(None, "feature_descriptors_missing", {})

    matches = cv2.BFMatcher().knnMatch(template_descriptors, image_descriptors, k=2)
    good_matches = [
        pair[0]
        for pair in matches
        if len(pair) == 2 and pair[0].distance < 0.7 * pair[1].distance
    ]
    alignment = config["template_alignment"]
    if len(good_matches) < alignment["minimum_inliers"]:
        return TemplateFeatureAttempt(
            None,
            "feature_matches_insufficient",
            {"featureGoodMatches": len(good_matches)},
        )

    source_points = np.float32(
        [template_keypoints[match.queryIdx].pt for match in good_matches]
    )
    destination_points = np.float32(
        [image_keypoints[match.trainIdx].pt for match in good_matches]
    )
    homography, inlier_mask = cv2.findHomography(
        source_points, destination_points, cv2.RANSAC, 5.0
    )
    if homography is None or inlier_mask is None:
        return TemplateFeatureAttempt(
            None,
            "feature_homography_failed",
            {"featureGoodMatches": len(good_matches)},
        )
    inlier_count = int(inlier_mask.sum())
    inlier_ratio = inlier_count / len(good_matches)
    if (
        inlier_count < alignment["minimum_inliers"]
        or inlier_ratio < alignment["minimum_inlier_ratio"]
    ):
        return TemplateFeatureAttempt(
            None,
            "feature_inliers_insufficient",
            {
                "featureGoodMatches": len(good_matches),
                "featureInliers": inlier_count,
                "featureInlierRatio": round(inlier_ratio, 4),
            },
        )

    inlier_points = source_points[inlier_mask.ravel().astype(bool)]
    x_span_ratio = (inlier_points[:, 0].max() - inlier_points[:, 0].min()) / template.shape[1]
    y_span_ratio = (inlier_points[:, 1].max() - inlier_points[:, 1].min()) / template.shape[0]
    diagnostics = {
        "featureGoodMatches": len(good_matches),
        "featureInliers": inlier_count,
        "featureInlierRatio": round(inlier_ratio, 4),
        "featureXSpanRatio": round(float(x_span_ratio), 4),
        "featureYSpanRatio": round(float(y_span_ratio), 4),
    }
    if (
        x_span_ratio < alignment["minimum_x_span_ratio"]
        or y_span_ratio < alignment["minimum_y_span_ratio"]
    ):
        return TemplateFeatureAttempt(None, "feature_distribution_insufficient", diagnostics)

    template_corners = np.float32(
        [[[0, 0], [template.shape[1] - 1, 0], [template.shape[1] - 1, template.shape[0] - 1], [0, template.shape[0] - 1]]]
    )
    projected = cv2.perspectiveTransform(template_corners, homography)[0]
    image_height, image_width = image.shape[:2]
    # Reject accidental matches to an unrelated image, but permit a small crop.
    margin = alignment["maximum_projected_margin_ratio"]
    if (
        np.any(projected[:, 0] < -margin * image_width)
        or np.any(projected[:, 0] > (1 + margin) * image_width)
        or np.any(projected[:, 1] < -margin * image_height)
        or np.any(projected[:, 1] > (1 + margin) * image_height)
    ):
        return TemplateFeatureAttempt(None, "feature_projection_invalid", diagnostics)
    if abs(cv2.contourArea(projected.astype(np.float32))) < 0.05 * image_width * image_height:
        return TemplateFeatureAttempt(None, "feature_projection_too_small", diagnostics)

    try:
        inverse_homography = np.linalg.inv(homography)
    except np.linalg.LinAlgError:
        return TemplateFeatureAttempt(None, "feature_inverse_failed", diagnostics)
    return TemplateFeatureAttempt(
        cv2.warpPerspective(
            image,
            inverse_homography,
            (template.shape[1], template.shape[0]),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        ),
        "success",
        diagnostics,
    )


def _fine_align(image: np.ndarray, template: np.ndarray, config: dict) -> np.ndarray:
    alignment = config["fine_alignment"]
    if not alignment["enabled"]:
        return image

    template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    warp = np.eye(2, 3, dtype=np.float32)
    criteria = (
        cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
        50,
        0.0001,
    )
    try:
        correlation, warp = cv2.findTransformECC(
            template_gray,
            image_gray,
            warp,
            cv2.MOTION_TRANSLATION,
            criteria,
            None,
            5,
        )
    except cv2.error:
        return image

    shift = float(np.hypot(warp[0, 2], warp[1, 2]))
    if correlation < alignment["minimum_correlation"] or shift > alignment["maximum_translation_px"]:
        return image

    return cv2.warpAffine(
        image,
        warp,
        (template.shape[1], template.shape[0]),
        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _paper_contour_diagnostics(image: np.ndarray, config: dict) -> dict[str, float | int | str | bool]:
    """Return geometry-only paper detection diagnostics; never image contents."""
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 45, 135)
    edges = cv2.morphologyEx(
        edges, cv2.MORPH_CLOSE, np.ones((5, 5), dtype=np.uint8), iterations=2
    )
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    quadrilateral_areas: list[float] = []
    for contour in contours:
        approximation = cv2.approxPolyDP(
            contour, 0.02 * cv2.arcLength(contour, True), True
        )
        if len(approximation) == 4 and cv2.isContourConvex(approximation):
            quadrilateral_areas.append(cv2.contourArea(contour) / (width * height))

    largest_area = max(quadrilateral_areas, default=0.0)
    minimum_area = float(config["document_detection"]["minimum_area_ratio"])
    return {
        "paperContourCode": "paper_contour_detected"
        if largest_area >= minimum_area
        else "paper_contour_too_small",
        "paperQuadrilateralCount": len(quadrilateral_areas),
        "paperLargestAreaRatio": round(float(largest_area), 4),
        "paperMinimumAreaRatio": minimum_area,
    }


def _checkbox_frame_quality(
    aligned_image: np.ndarray, template: np.ndarray, config: dict
) -> dict[str, float | int | bool]:
    """Compare only printed checkbox frames after correction, not answer content."""
    quality_config = config["alignment_quality"]
    margin = int(quality_config["checkbox_frame_margin_px"])
    search = int(quality_config["checkbox_frame_search_px"])
    template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    scan_gray = cv2.cvtColor(aligned_image, cv2.COLOR_BGR2GRAY)
    scores: list[float] = []
    shifts: list[tuple[float, float]] = []
    options = config["performance"]["options"] + config["age"]["options"]

    for option in options:
        x, y, width, height = option["box"]
        patch = template_gray[y - margin : y + height + margin, x - margin : x + width + margin]
        search_area = scan_gray[
            y - margin - search : y + height + margin + search,
            x - margin - search : x + width + margin + search,
        ]
        if patch.size == 0 or search_area.shape[0] < patch.shape[0] or search_area.shape[1] < patch.shape[1]:
            scores.append(-1.0)
            continue
        match = cv2.matchTemplate(search_area, patch, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(match)
        scores.append(float(score))
        shifts.append((float(location[0] - search), float(location[1] - search)))

    median_shift = np.median(np.asarray(shifts), axis=0) if shifts else np.array([999.0, 999.0])
    mean_score = float(np.mean(scores)) if scores else -1.0
    min_score = float(np.min(scores)) if scores else -1.0
    passed = (
        mean_score >= quality_config["minimum_mean_score"]
        and min_score >= quality_config["minimum_min_score"]
    )
    return {
        "checkboxFrameMeanScore": round(mean_score, 4),
        "checkboxFrameMinScore": round(min_score, 4),
        "checkboxFrameMedianShiftX": round(float(median_shift[0]), 2),
        "checkboxFrameMedianShiftY": round(float(median_shift[1]), 2),
        "checkboxFrameQualityPassed": passed,
    }


def correct_document_with_diagnostics(
    image: np.ndarray,
) -> tuple[np.ndarray, dict[str, float | int | str | bool]]:
    """Correct a document and expose only non-PII geometric quality metrics."""
    config = load_template_config()
    template = load_template_image()
    corners = find_document_corners(image, config)
    paper_diagnostics = _paper_contour_diagnostics(image, config)
    image_height, image_width = image.shape[:2]
    full_image_corners = _order_corners(
        np.array(
            [[0, 0], [image_width - 1, 0], [image_width - 1, image_height - 1], [0, image_height - 1]],
            dtype=np.float32,
        )
    )
    if np.allclose(corners, full_image_corners):
        feature_attempt = _align_with_template_features(image, template, config)
        if feature_attempt.aligned_image is None:
            raise DocumentDetectionError(
                "テンプレート位置合わせに失敗しました。アンケート全体が写るように撮影してください。",
                code=feature_attempt.code,
                diagnostics={
                    "correctionMethod": "template_feature",
                    **paper_diagnostics,
                    **feature_attempt.diagnostics,
                },
            )
        aligned = _fine_align(feature_attempt.aligned_image, template, config)
        diagnostics: dict[str, float | int | str | bool] = {
            "correctionMethod": "template_feature",
            **paper_diagnostics,
            **feature_attempt.diagnostics,
        }
    else:
        top_width = np.linalg.norm(corners[1] - corners[0])
        left_height = np.linalg.norm(corners[3] - corners[0])
        target_width = config["reference"]["width"]
        target_height = config["reference"]["height"]

        if top_width >= left_height:
            output_size = (target_height, target_width)
        else:
            output_size = (target_width, target_height)
        destination = np.array(
            [
                [0, 0],
                [output_size[0] - 1, 0],
                [output_size[0] - 1, output_size[1] - 1],
                [0, output_size[1] - 1],
            ],
            dtype=np.float32,
        )
        transform = cv2.getPerspectiveTransform(corners, destination)
        warped = cv2.warpPerspective(image, transform, output_size)
        aligned = _fine_align(_choose_upright_orientation(warped, template), template, config)
        diagnostics = {"correctionMethod": "paper_contour", **paper_diagnostics}

    quality = _checkbox_frame_quality(aligned, template, config)
    diagnostics.update(quality)
    if not quality["checkboxFrameQualityPassed"]:
        # If an apparent paper contour was actually an internal printed box,
        # retry with feature alignment.  The fallback still must pass the same
        # checkbox-frame quality gate before it is accepted.
        if diagnostics["correctionMethod"] == "paper_contour":
            feature_attempt = _align_with_template_features(image, template, config)
            if feature_attempt.aligned_image is not None:
                fallback_aligned = _fine_align(feature_attempt.aligned_image, template, config)
                fallback_quality = _checkbox_frame_quality(fallback_aligned, template, config)
                if fallback_quality["checkboxFrameQualityPassed"]:
                    return fallback_aligned, {
                        "correctionMethod": "template_feature_fallback",
                        "paperContourFallback": "post_transform_quality_failed",
                        **paper_diagnostics,
                        **feature_attempt.diagnostics,
                        **fallback_quality,
                    }
        raise DocumentDetectionError(
            "補正後のテンプレート位置合わせを確認できません。アンケート全体が写るように撮影してください。",
            code="post_transform_quality_failed",
            diagnostics=diagnostics,
        )
    return aligned, diagnostics


def correct_document(image: np.ndarray) -> np.ndarray:
    """Perspective-correct a page and return its fixed template coordinate system."""
    return correct_document_with_diagnostics(image)[0]


def measure_checkboxes(
    aligned_image: np.ndarray,
    template_image: np.ndarray,
    options: Iterable[dict],
    checkbox_config: dict,
) -> list[CheckboxMeasurement]:
    """Measure added pen ink inside boxes, excluding the printed square border."""
    scan_gray = cv2.cvtColor(aligned_image, cv2.COLOR_BGR2GRAY)
    template_gray = cv2.cvtColor(template_image, cv2.COLOR_BGR2GRAY)
    inset = int(checkbox_config["inner_inset_px"])
    darkness = int(checkbox_config["added_ink_darkness"])
    readings: list[CheckboxMeasurement] = []

    for option in options:
        x, y, width, height = (int(value) for value in option["box"])
        inner_scan = scan_gray[y + inset : y + height - inset, x + inset : x + width - inset]
        inner_template = template_gray[
            y + inset : y + height - inset, x + inset : x + width - inset
        ]
        if inner_scan.size == 0 or inner_scan.shape != inner_template.shape:
            raise ScanError("チェックボックスの座標設定が不正です。")

        # Correct a uniform exposure shift from printed-template background
        # around the box.  The checkbox interior itself may be fully covered by
        # a handwritten X, so it must not be used as the exposure reference.
        margin = 5
        left, top = max(0, x - margin), max(0, y - margin)
        right, bottom = min(scan_gray.shape[1], x + width + margin), min(
            scan_gray.shape[0], y + height + margin
        )
        surrounding_scan = scan_gray[top:bottom, left:right]
        surrounding_template = template_gray[top:bottom, left:right]
        background_pixels = surrounding_template >= 245
        if np.any(background_pixels):
            exposure_shift = float(
                np.median(surrounding_template[background_pixels])
                - np.median(surrounding_scan[background_pixels])
            )
        else:
            exposure_shift = 0.0
        normalized_scan = np.clip(inner_scan.astype(np.float32) + exposure_shift, 0, 255)
        added_ink = inner_template.astype(np.float32) - normalized_scan
        ink_ratio = float(np.mean(added_ink >= darkness))
        readings.append(CheckboxMeasurement(str(option["value"]), ink_ratio))
    return readings


def result_for_single_select(readings: list[CheckboxMeasurement], checkbox_config: dict) -> FieldResult:
    threshold = float(checkbox_config["checked_ink_ratio"])
    band = float(checkbox_config["uncertain_band"])
    selected = [reading for reading in readings if reading.ink_ratio >= threshold]
    candidates = [reading.value for reading in selected]
    near_threshold = any(abs(reading.ink_ratio - threshold) <= band for reading in readings)

    if len(selected) == 1:
        ratio = selected[0].ink_ratio
        confidence = min(1.0, max(0.0, (ratio - threshold) / (1.0 - threshold)))
        return FieldResult(
            value=selected[0].value,
            confidence=confidence,
            needsReview=near_threshold,
            candidates=candidates,
            status="uncertain" if near_threshold else "selected",
        )
    if len(selected) > 1:
        return FieldResult(
            confidence=0,
            needsReview=True,
            candidates=candidates,
            status="multiple",
        )
    return FieldResult(confidence=0, needsReview=True, candidates=[], status="none")


def result_for_multiple_select(
    readings: list[CheckboxMeasurement], checkbox_config: dict
) -> FieldResult:
    """Return all checked choices; ambiguity applies only near the threshold."""
    threshold = float(checkbox_config["checked_ink_ratio"])
    band = float(checkbox_config["uncertain_band"])
    selected = [reading for reading in readings if reading.ink_ratio >= threshold]
    candidates = [reading.value for reading in selected]
    near_threshold = any(abs(reading.ink_ratio - threshold) <= band for reading in readings)
    if not selected:
        return FieldResult(confidence=0, needsReview=True, candidates=[], status="none")
    confidence = min(
        1.0,
        max(0.0, min((reading.ink_ratio - threshold) / (1.0 - threshold) for reading in selected)),
    )
    return FieldResult(
        value=", ".join(candidates),
        confidence=confidence,
        needsReview=near_threshold,
        candidates=candidates,
        status="uncertain" if near_threshold else "selected",
    )


def _unavailable_field() -> FieldResult:
    return FieldResult(confidence=0, needsReview=True, status="unavailable")


def _with_selected_details(
    selection: FieldResult,
    options: list[dict],
    detail_results: dict[str, FieldResult],
) -> FieldResult:
    """Attach OCR text only to its selected option, without inventing content."""
    if not selection.candidates:
        return selection

    values: list[str] = []
    needs_review = selection.needsReview
    confidence = selection.confidence
    selected = set(selection.candidates)
    for option in options:
        value = str(option["value"])
        if value not in selected:
            continue
        detail_key = option.get("detail_field")
        detail = detail_results.get(str(detail_key)) if detail_key else None
        if detail is not None:
            needs_review = needs_review or detail.needsReview
            confidence = min(confidence, detail.confidence)
            if detail.value:
                value = f"{value}（{detail.value}）"
        values.append(value)

    return FieldResult(
        value=", ".join(values),
        confidence=confidence,
        needsReview=needs_review,
        candidates=values,
        status="uncertain" if needs_review and selection.status == "selected" else selection.status,
    )


POSTAL_CODE_PATTERN = re.compile(r"\d{3}-\d{4}\Z")
EMAIL_PATTERN = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+\Z")


def _validate_postal_code(result: FieldResult) -> FieldResult:
    value = result.value.replace("〒", "")
    is_valid = bool(POSTAL_CODE_PATTERN.fullmatch(value.strip()))
    return result.model_copy(
        update={
            "value": value,
            "needsReview": result.needsReview or bool(value) and not is_valid,
            "status": "uncertain" if value and not is_valid else result.status,
        }
    )


def _validate_email(result: FieldResult) -> FieldResult:
    is_valid = bool(EMAIL_PATTERN.fullmatch(result.value.strip()))
    return result.model_copy(
        update={
            "needsReview": result.needsReview or bool(result.value) and not is_valid,
            "status": "uncertain" if result.value and not is_valid else result.status,
        }
    )


def _scan_aligned_front(aligned_image: np.ndarray) -> ScanFields:
    config = load_template_config()
    template = load_template_image()
    checkbox_config = config["checkbox"]
    performance = result_for_single_select(
        measure_checkboxes(
            aligned_image, template, config["performance"]["options"], checkbox_config
        ),
        checkbox_config,
    )
    age = result_for_single_select(
        measure_checkboxes(aligned_image, template, config["age"]["options"], checkbox_config),
        checkbox_config,
    )
    trigger = result_for_multiple_select(
        measure_checkboxes(aligned_image, template, config["trigger"]["options"], checkbox_config),
        checkbox_config,
    )
    media = result_for_multiple_select(
        measure_checkboxes(aligned_image, template, config["media"]["options"], checkbox_config),
        checkbox_config,
    )
    reservation = result_for_single_select(
        measure_checkboxes(aligned_image, template, config["reservation"]["options"], checkbox_config),
        checkbox_config,
    )
    return ScanFields(
        performance=performance,
        age=age,
        trigger=trigger,
        media=media,
        reservation=reservation,
        message=_unavailable_field(),
        name=_unavailable_field(),
        mailingName=_unavailable_field(),
        postalCode=_unavailable_field(),
        address=_unavailable_field(),
        email=_unavailable_field(),
    )


def scan_front(image_bytes: bytes) -> ScanFields:
    """Complete Phase 1–3 processing without persisting the uploaded image."""
    image = decode_image(image_bytes)
    return _scan_aligned_front(correct_document(image))


def scan_front_with_ocr(
    image_bytes: bytes, ocr_client: OcrClient | None
) -> ScanFields:
    """Phase 5 scan with per-field, in-memory OCR after template alignment."""
    image = decode_image(image_bytes)
    aligned_image = correct_document(image)
    fields = _scan_aligned_front(aligned_image)
    config = load_template_config()
    text_results = {
        field_name: recognize_text_field(aligned_image, config[field_name], ocr_client)
        for field_name in ("message", "name", "mailing_name", "postal_code", "address", "email")
    }
    detail_results: dict[str, FieldResult] = {}
    for selection, config_key in (
        (fields.trigger, "trigger"),
        (fields.media, "media"),
        (fields.reservation, "reservation"),
    ):
        for option in config[config_key]["options"]:
            detail_key = option.get("detail_field")
            if detail_key and option["value"] in selection.candidates:
                detail_results[detail_key] = recognize_text_field(
                    aligned_image, config[detail_key], ocr_client
                )

    return fields.model_copy(
        update={
            "trigger": _with_selected_details(fields.trigger, config["trigger"]["options"], detail_results),
            "media": _with_selected_details(fields.media, config["media"]["options"], detail_results),
            "reservation": _with_selected_details(
                fields.reservation, config["reservation"]["options"], detail_results
            ),
            "message": text_results["message"],
            "name": text_results["name"],
            "mailingName": text_results["mailing_name"],
            "postalCode": _validate_postal_code(text_results["postal_code"]),
            "address": text_results["address"],
            "email": _validate_email(text_results["email"]),
        }
    )


def scan_front_with_message(image_bytes: bytes, ocr_client: OcrClient | None) -> ScanFields:
    """Compatibility wrapper retained for the Phase 4 public processing entry point."""
    return scan_front_with_ocr(image_bytes, ocr_client)


def scan_front_with_diagnostics(
    image_bytes: bytes,
) -> tuple[ScanFields, dict[str, float | int | str | bool]]:
    """Phase 3 scan with non-PII correction diagnostics for local validation only."""
    image = decode_image(image_bytes)
    aligned_image, diagnostics = correct_document_with_diagnostics(image)
    return _scan_aligned_front(aligned_image), diagnostics
