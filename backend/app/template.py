"""Reference questionnaire loading and template configuration."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

import cv2
import numpy as np
import pymupdf


class TemplateError(RuntimeError):
    """The fixed questionnaire template cannot be loaded safely."""


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(__file__).parent / "config" / "survey_template.json"


@lru_cache(maxsize=1)
def load_template_config() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as config_file:
        return json.load(config_file)


def reference_pdf_path() -> Path:
    """Find the one checked-in reference PDF, including the current legacy filename."""
    reference_directory = PROJECT_ROOT / "reference"
    preferred = reference_directory / "questionnaire_blank.pdf"
    if preferred.exists():
        return preferred

    pdf_files = list(reference_directory.glob("*.pdf"))
    if len(pdf_files) == 1:
        return pdf_files[0]
    raise TemplateError("基準アンケートPDFが見つかりません。")


@lru_cache(maxsize=1)
def load_template_image() -> np.ndarray:
    """Render the PDF in memory; no rasterized questionnaire is stored on disk."""
    config = load_template_config()
    scale = float(config["reference"]["render_scale"])

    try:
        document = pymupdf.open(reference_pdf_path())
        try:
            if document.page_count != 1:
                raise TemplateError("基準アンケートPDFは1ページである必要があります。")
            pixmap = document[0].get_pixmap(
                matrix=pymupdf.Matrix(scale, scale), alpha=False
            )
        finally:
            document.close()
    except TemplateError:
        raise
    except Exception as error:  # PDF parser errors must not expose input data.
        raise TemplateError("基準アンケートPDFを読み込めません。") from error

    samples = np.frombuffer(pixmap.samples, dtype=np.uint8)
    image = samples.reshape(pixmap.height, pixmap.width, pixmap.n)
    if pixmap.n == 1:
        rendered = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif pixmap.n == 3:
        rendered = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    elif pixmap.n == 4:
        rendered = cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)
    else:
        raise TemplateError("基準アンケートPDFの色形式に対応していません。")

    expected_size = (config["reference"]["height"], config["reference"]["width"])
    if rendered.shape[:2] != expected_size:
        raise TemplateError("基準アンケートの画像サイズが設定と一致しません。")
    return rendered
