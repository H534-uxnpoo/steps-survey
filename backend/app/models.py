from typing import Literal

from pydantic import BaseModel, Field


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
