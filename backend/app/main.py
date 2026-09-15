"""FastAPI entry point for the Phase 1–3 scan flow."""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .image_processing import DocumentDetectionError, ScanError, scan_front_with_message
from .models import ScanResponse, SubmissionRequest, SubmissionResponse
from .ocr import get_message_ocr_client
from .sheets import SheetsError, get_sheets_provider_from_env

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png"}

app = FastAPI(title="STEPS Survey Scanner", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    request: Request, _error: RequestValidationError
) -> JSONResponse:
    """Return a stable validation code without echoing request data."""
    code = (
        "submission_validation_error"
        if request.url.path == "/api/submissions"
        else "validation_error"
    )
    return JSONResponse(
        status_code=422,
        content={"detail": {"code": code}},
    )


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/api/scan/front", response_model=ScanResponse)
async def scan_front_image(image: UploadFile = File(...)) -> ScanResponse:
    """Scan a JPEG/PNG in memory; Vision receives only the message-field crop."""
    if image.content_type not in ALLOWED_MEDIA_TYPES:
        await image.close()
        raise HTTPException(status_code=415, detail="JPEGまたはPNG形式の画像を選択してください。")

    try:
        image_bytes = await image.read(MAX_UPLOAD_BYTES + 1)
    finally:
        # Starlette closes/removes a spooled multipart temporary file here.
        await image.close()

    if len(image_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="画像ファイルは12MB以下にしてください。")

    try:
        fields = scan_front_with_message(image_bytes, get_message_ocr_client())
    except DocumentDetectionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ScanError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return ScanResponse(
        scanId=str(uuid4()),
        fields=fields,
        needsReview=(
            any(
                getattr(fields, field_name).needsReview
                or getattr(fields, field_name).detailNeedsReview
                for field_name in type(fields).model_fields
            )
        ),
    )


@app.post("/api/submissions", response_model=SubmissionResponse)
def submit_confirmed_submission(payload: SubmissionRequest) -> SubmissionResponse:
    """Append only the 11 values currently shown on the confirmation screen."""
    try:
        provider = get_sheets_provider_from_env()
        provider.append_row(payload.sheet_row())
    except SheetsError as error:
        if error.code == "sheet_header_mismatch":
            status_code = 409
        elif error.code == "sheets_api_error":
            status_code = 502
        else:
            # Disabled, unconfigured, and unavailable ADC paths never look
            # like a successful save to the browser.
            status_code = 503
        safe_code = (
            error.code
            if error.code in {"sheet_header_mismatch", "sheets_api_error"}
            else "sheets_unavailable"
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": safe_code},
        ) from error
    except Exception as error:
        # Provider implementations must not leak provider messages or row
        # contents through an unexpected exception path.
        raise HTTPException(
            status_code=502,
            detail={"code": "sheets_api_error"},
        ) from error

    return SubmissionResponse(success=True)
