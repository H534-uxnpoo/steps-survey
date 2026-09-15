import cv2
import numpy as np
import pytest

from app import image_processing
from app.image_processing import (
    DocumentDetectionError,
    TemplateFeatureAttempt,
    correct_document_with_diagnostics,
    correct_document,
    measure_checkboxes,
    result_for_multiple_select,
    result_for_single_select,
)
from app.template import load_template_config, load_template_image


@pytest.fixture(scope="module")
def template_and_config():
    return load_template_image().copy(), load_template_config()


def marked_template(template, options_to_mark, config):
    image = template.copy()
    all_options = config["performance"]["options"] + config["age"]["options"]
    for option in all_options:
        if option["value"] not in options_to_mark:
            continue
        x, y, width, height = option["box"]
        inset = config["checkbox"]["inner_inset_px"] + 1
        cv2.line(
            image,
            (x + inset, y + inset),
            (x + width - inset - 1, y + height - inset - 1),
            (0, 0, 0),
            2,
        )
        cv2.line(
            image,
            (x + width - inset - 1, y + inset),
            (x + inset, y + height - inset - 1),
            (0, 0, 0),
            2,
        )
    return image


def test_checkbox_measurement_selects_only_added_ink(template_and_config):
    template, config = template_and_config
    image = marked_template(template, {"12日(土)17:30-", "40代"}, config)

    performance = result_for_single_select(
        measure_checkboxes(
            image, template, config["performance"]["options"], config["checkbox"]
        ),
        config["checkbox"],
    )
    age = result_for_single_select(
        measure_checkboxes(image, template, config["age"]["options"], config["checkbox"]),
        config["checkbox"],
    )

    assert performance.value == "12日(土)17:30-"
    assert performance.status == "selected"
    assert age.value == "40代"
    assert age.status == "selected"


def test_blank_template_checkbox_frames_are_never_selected(template_and_config):
    template, config = template_and_config

    for field_name in ("performance", "age", "trigger", "media", "reservation"):
        readings = measure_checkboxes(
            template,
            template,
            config[field_name]["options"],
            config["checkbox"],
        )
        result = (
            result_for_multiple_select(readings, config["checkbox"])
            if config[field_name].get("multiple_select")
            else result_for_single_select(readings, config["checkbox"])
        )
        assert result.status == "none"
        assert result.candidates == []


def test_multiple_checkbox_candidates_require_review(template_and_config):
    template, config = template_and_config
    image = marked_template(template, {"10代以下", "20代"}, config)

    result = result_for_single_select(
        measure_checkboxes(image, template, config["age"]["options"], config["checkbox"]),
        config["checkbox"],
    )

    assert result.value == ""
    assert result.status == "multiple"
    assert result.needsReview is True
    assert result.candidates == ["10代以下", "20代"]


def test_perspective_correction_restores_fixed_template_size(template_and_config):
    template, config = template_and_config
    height, width = template.shape[:2]
    canvas = np.full((height + 260, width + 220, 3), 185, dtype=np.uint8)
    source = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    destination = np.float32(
        [[95, 65], [width + 65, 110], [width + 20, height + 185], [135, height + 140]]
    )
    transform = cv2.getPerspectiveTransform(source, destination)
    warped = cv2.warpPerspective(template, transform, (canvas.shape[1], canvas.shape[0]))
    page_mask = cv2.warpPerspective(
        np.full((height, width), 255, dtype=np.uint8), transform, (canvas.shape[1], canvas.shape[0])
    )
    canvas[page_mask > 0] = warped[page_mask > 0]

    corrected = correct_document(canvas)

    assert corrected.shape[:2] == (config["reference"]["height"], config["reference"]["width"])


def test_combined_light_camera_variation_preserves_checkbox_coordinates(
    template_and_config,
):
    """A public, in-memory camera-like transform must retain fixed-form choices."""
    template, config = template_and_config
    height, width = template.shape[:2]
    marked = template.copy()
    selected_indices = {
        "performance": 1,
        "age": 2,
        "trigger": 5,
        "media": 1,
        "reservation": 0,
    }

    for field_name, option_index in selected_indices.items():
        x, y, box_width, box_height = config[field_name]["options"][option_index]["box"]
        inset = config["checkbox"]["inner_inset_px"] + 1
        cv2.line(
            marked,
            (x + inset, y + inset),
            (x + box_width - inset - 1, y + box_height - inset - 1),
            (0, 0, 0),
            2,
        )
        cv2.line(
            marked,
            (x + box_width - inset - 1, y + inset),
            (x + inset, y + box_height - inset - 1),
            (0, 0, 0),
            2,
        )

    # This single synthetic scene combines mild rotation/perspective, reduced
    # contrast, a brightness shift, and light blur.  It uses only the public
    # blank form and artificial marks.
    marked = cv2.convertScaleAbs(marked, alpha=0.78, beta=26)
    canvas = np.full((height + 380, width + 420, 3), 190, dtype=np.uint8)
    source = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    destination = np.float32(
        [[170, 115], [width + 225, 175], [width + 130, height + 290], [95, height + 210]]
    )
    transform = cv2.getPerspectiveTransform(source, destination)
    warped = cv2.warpPerspective(marked, transform, (canvas.shape[1], canvas.shape[0]))
    page_mask = cv2.warpPerspective(
        np.full((height, width), 255, dtype=np.uint8), transform, (canvas.shape[1], canvas.shape[0])
    )
    canvas[page_mask > 0] = warped[page_mask > 0]
    captured = cv2.GaussianBlur(canvas, (3, 3), 0)

    corrected, diagnostics = correct_document_with_diagnostics(captured)

    assert corrected.shape[:2] == (height, width)
    assert diagnostics["checkboxFrameQualityPassed"] is True
    for field_name, option_index in selected_indices.items():
        readings = measure_checkboxes(
            corrected,
            template,
            config[field_name]["options"],
            config["checkbox"],
        )
        result = (
            result_for_multiple_select(readings, config["checkbox"])
            if config[field_name].get("multiple_select")
            else result_for_single_select(readings, config["checkbox"])
        )
        assert result.value == config[field_name]["options"][option_index]["value"]
        assert result.needsReview is False


def test_extreme_one_sided_crop_is_rejected_safely(template_and_config):
    """A scan missing half the fixed form must never become a successful alignment."""
    template, _ = template_and_config
    one_sided_crop = template[:, : template.shape[1] // 2].copy()

    with pytest.raises(DocumentDetectionError):
        correct_document(one_sided_crop)


def test_feature_preprocessing_uses_clahe_only_after_raw_alignment_fails(
    monkeypatch, template_and_config
):
    """Illumination fallback must preserve the raw strategy's acceptance gates."""
    template, config = template_and_config
    calls: list[str] = []

    def fake_alignment(_image, _template, _config, *, preprocessing):
        calls.append(preprocessing)
        if preprocessing == "raw":
            return TemplateFeatureAttempt(
                None,
                "feature_distribution_insufficient",
                {"featureGoodMatches": 17},
            )
        return TemplateFeatureAttempt(
            template.copy(),
            "success",
            {"featureGoodMatches": 21, "featureInliers": 18},
        )

    monkeypatch.setattr(
        image_processing, "_align_with_template_features_once", fake_alignment
    )

    attempt = image_processing._align_with_template_features(template, template, config)

    assert calls == ["raw", "clahe"]
    assert attempt.code == "success"
    assert attempt.diagnostics["featurePreprocessing"] == "clahe"


def test_borderless_scan_uses_printed_template_features(template_and_config):
    template, config = template_and_config
    height, width = template.shape[:2]
    source = marked_template(template, {"13日(日)12:30-"}, config)
    canvas = np.full((1920, 1440, 3), 255, dtype=np.uint8)
    transform = np.float32([[1.11, -0.02, 60], [-0.02, 1.08, -28], [0, 0, 1]])
    warped = cv2.warpPerspective(source, transform, (canvas.shape[1], canvas.shape[0]))
    page_mask = cv2.warpPerspective(
        np.full((height, width), 255, dtype=np.uint8), transform, (canvas.shape[1], canvas.shape[0])
    )
    canvas[page_mask > 0] = warped[page_mask > 0]

    corrected = correct_document(canvas)
    performance = result_for_single_select(
        measure_checkboxes(
            corrected, template, config["performance"]["options"], config["checkbox"]
        ),
        config["checkbox"],
    )

    assert corrected.shape[:2] == (height, width)
    assert performance.value == "13日(日)12:30-"


def test_low_quality_paper_contour_uses_template_feature_fallback(
    monkeypatch, template_and_config
):
    template, _ = template_and_config
    height, width = template.shape[:2]
    non_full_corners = np.float32(
        [[1, 1], [width - 2, 1], [width - 2, height - 2], [1, height - 2]]
    )
    quality_results = iter(
        [
            {"checkboxFrameQualityPassed": False},
            {"checkboxFrameQualityPassed": True},
        ]
    )
    monkeypatch.setattr(
        image_processing,
        "find_document_corners",
        lambda *_: non_full_corners,
    )
    monkeypatch.setattr(
        image_processing,
        "_checkbox_frame_quality",
        lambda *_: next(quality_results),
    )
    monkeypatch.setattr(
        image_processing,
        "_align_with_template_features",
        lambda *_: TemplateFeatureAttempt(template.copy(), "success", {}),
    )

    _, diagnostics = correct_document_with_diagnostics(template)

    assert diagnostics["correctionMethod"] == "template_feature_fallback"
    assert diagnostics["paperContourFallback"] == "post_transform_quality_failed"
