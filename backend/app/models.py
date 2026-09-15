import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


SHEET_HEADERS = (
    "公演回",
    "年齢",
    "きっかけ",
    "宣伝媒体",
    "予約のスムーズさ",
    "メッセージ",
    "名前",
    "案内希望者名",
    "郵便番号",
    "住所",
    "メアド",
)

POSTAL_CODE_PATTERN = re.compile(r"(?:〒)?\d{3}-\d{4}\Z")
EMAIL_PATTERN = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+\Z")


class FieldResult(BaseModel):
    """A recognised field; candidates are retained for ambiguous checkboxes."""

    value: str = ""
    confidence: float = Field(ge=0, le=1)
    needsReview: bool
    detailNeedsReview: bool = False
    candidates: list[str] = Field(default_factory=list)
    status: Literal[
        "selected", "none", "multiple", "uncertain", "recognized", "unavailable"
    ]


class ScanFields(BaseModel):
    performance: FieldResult
    age: FieldResult
    trigger: FieldResult
    media: FieldResult
    reservation: FieldResult
    message: FieldResult
    name: FieldResult
    mailingName: FieldResult
    postalCode: FieldResult
    address: FieldResult
    email: FieldResult


class ScanResponse(BaseModel):
    scanId: str
    fields: ScanFields
    needsReview: bool


class BackScanResponse(BaseModel):
    """OCR result for a free-form back-side image."""

    message: FieldResult
    needsReview: bool


class SubmissionRequest(BaseModel):
    """The exact 11 user-confirmed values that become one Sheets row."""

    model_config = ConfigDict(extra="forbid", strict=True)

    performance: str = Field(max_length=120)
    age: str = Field(max_length=64)
    trigger: str = Field(max_length=1_000)
    media: str = Field(max_length=1_000)
    reservation: str = Field(max_length=1_000)
    message: str = Field(max_length=10_000)
    name: str = Field(max_length=500)
    mailingName: str = Field(max_length=500)
    postalCode: str = Field(max_length=32)
    address: str = Field(max_length=5_000)
    email: str = Field(max_length=500)

    @field_validator("postalCode")
    @classmethod
    def validate_postal_code(cls, value: str) -> str:
        if value and not POSTAL_CODE_PATTERN.fullmatch(value):
            raise ValueError("postal_code_invalid")
        return value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if value and not EMAIL_PATTERN.fullmatch(value):
            raise ValueError("email_invalid")
        return value

    def sheet_row(self) -> list[str]:
        """Keep user-confirmed text exactly as supplied and in fixed A:K order."""
        return [
            self.performance,
            self.age,
            self.trigger,
            self.media,
            self.reservation,
            self.message,
            self.name,
            self.mailingName,
            self.postalCode,
            self.address,
            self.email,
        ]


class SubmissionResponse(BaseModel):
    success: bool
