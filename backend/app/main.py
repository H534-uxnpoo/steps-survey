"""FastAPI entry point for the Phase 1–3 scan flow."""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .image_processing import DocumentDetectionError, ScanError, scan_front_with_message
from .models import ScanResponse
from .ocr import get_message_ocr_client

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
                for field_name in type(fields).model_fields
            )
        ),
    )
