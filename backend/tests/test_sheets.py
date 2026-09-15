from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.sheets import (
    GoogleSheetsProvider,
    SHEET_HEADERS,
    SheetsConfig,
    SheetsError,
    get_sheets_provider_from_env,
)


@dataclass
class FakeRequest:
    response: dict[str, Any] | None = None
    error: Exception | None = None

    def execute(self) -> dict[str, Any]:
        if self.error is not None:
            raise self.error
        return self.response or {}


@dataclass
class FakeValuesResource:
    header: list[str] = field(default_factory=lambda: list(SHEET_HEADERS))
    get_error: Exception | None = None
    append_error: Exception | None = None
    get_calls: list[dict[str, Any]] = field(default_factory=list)
    append_calls: list[dict[str, Any]] = field(default_factory=list)

    def get(self, **kwargs: Any) -> FakeRequest:
        self.get_calls.append(kwargs)
        return FakeRequest(response={"values": [self.header]}, error=self.get_error)

    def append(self, **kwargs: Any) -> FakeRequest:
        self.append_calls.append(kwargs)
        return FakeRequest(response={"updates": {"updatedRows": 1}}, error=self.append_error)


@dataclass
class FakeSpreadsheetsResource:
    values_resource: FakeValuesResource

    def values(self) -> FakeValuesResource:
        return self.values_resource


@dataclass
class FakeGoogleService:
    values_resource: FakeValuesResource

    def spreadsheets(self) -> FakeSpreadsheetsResource:
        return FakeSpreadsheetsResource(self.values_resource)


@dataclass
class FakeSheetsProvider:
    error_code: str | None = None
    rows: list[list[str]] = field(default_factory=list)

    def append_row(self, row: list[str]) -> None:
        if self.error_code is not None:
            raise SheetsError(self.error_code)
        self.rows.append(list(row))


@pytest.fixture
def submission_payload() -> dict[str, str]:
    """Clearly fictional values only; no survey contents are used in this test."""
    return {
        "performance": "PERFORMANCE",
        "age": "AGE",
        "trigger": "関係者の誘い（DUMMY RELATED）,その他（DUMMY TRIGGER）",
        "media": "X,その他（DUMMY MEDIA）",
        "reservation": "その他（DUMMY RESERVATION）",
        "message": "DUMMY MESSAGE",
        "name": "DUMMY NAME",
        "mailingName": "DUMMY MAILING NAME",
        "postalCode": "123-4567",
        "address": "DUMMY ADDRESS",
        "email": "dummy@example.test",
    }


def _provider(
    values_resource: FakeValuesResource,
    *,
    enabled: bool = True,
) -> GoogleSheetsProvider:
    return GoogleSheetsProvider(
        SheetsConfig(
            enabled=enabled,
            spreadsheet_id="test-spreadsheet-id",
            range="アンケート!A:K",
        ),
        service=FakeGoogleService(values_resource),
    )


def test_sheet_headers_are_fixed_to_the_eleven_submission_columns():
    assert SHEET_HEADERS == (
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


def test_google_provider_checks_header_then_appends_exact_eleven_cells(submission_payload):
    values = FakeValuesResource()
    provider = _provider(values)
    row = list(submission_payload.values())

    provider.append_row(row)

    assert values.get_calls == [
        {"spreadsheetId": "test-spreadsheet-id", "range": "アンケート!A1:K1"}
    ]
    assert values.append_calls == [
        {
            "spreadsheetId": "test-spreadsheet-id",
            "range": "アンケート!A:K",
            "valueInputOption": "RAW",
            "insertDataOption": "INSERT_ROWS",
            "body": {"values": [row]},
        }
    ]


def test_google_provider_does_not_append_when_disabled(submission_payload):
    values = FakeValuesResource()

    with pytest.raises(SheetsError, match="sheets_unavailable"):
        _provider(values, enabled=False).append_row(list(submission_payload.values()))

    assert values.get_calls == []
    assert values.append_calls == []


def test_default_environment_provider_is_not_a_success_path(monkeypatch):
    monkeypatch.delenv("SHEETS_ENABLED", raising=False)
    monkeypatch.delenv("SHEETS_SPREADSHEET_ID", raising=False)
    monkeypatch.delenv("SHEETS_RANGE", raising=False)

    provider = get_sheets_provider_from_env()

    with pytest.raises(SheetsError, match="sheets_unavailable"):
        provider.append_row([""] * len(SHEET_HEADERS))


def test_google_provider_does_not_append_when_header_mismatches(submission_payload):
    values = FakeValuesResource(header=["WRONG"] * len(SHEET_HEADERS))

    with pytest.raises(SheetsError, match="sheet_header_mismatch"):
        _provider(values).append_row(list(submission_payload.values()))

    assert len(values.get_calls) == 1
    assert values.append_calls == []


def test_google_provider_maps_google_api_failure_to_safe_error(submission_payload):
    values = FakeValuesResource(append_error=RuntimeError("network failure"))

    with pytest.raises(SheetsError, match="sheets_api_error"):
        _provider(values).append_row(list(submission_payload.values()))

    assert len(values.get_calls) == 1
    assert len(values.append_calls) == 1


def test_submission_api_maps_all_fields_to_one_ordered_row(monkeypatch, submission_payload):
    fake_provider = FakeSheetsProvider()
    monkeypatch.setattr("app.main.get_sheets_provider_from_env", lambda: fake_provider)

    response = TestClient(app).post("/api/submissions", json=submission_payload)

    assert response.status_code == 200
    assert response.json() == {"success": True}
    assert fake_provider.rows == [
        [
            "PERFORMANCE",
            "AGE",
            "関係者の誘い（DUMMY RELATED）,その他（DUMMY TRIGGER）",
            "X,その他（DUMMY MEDIA）",
            "その他（DUMMY RESERVATION）",
            "DUMMY MESSAGE",
            "DUMMY NAME",
            "DUMMY MAILING NAME",
            "123-4567",
            "DUMMY ADDRESS",
            "dummy@example.test",
        ]
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("postalCode", "12O-4567"),
        ("email", "not-an-email"),
    ],
)
def test_submission_api_rejects_invalid_postal_code_or_email(
    monkeypatch,
    submission_payload,
    field,
    value,
):
    fake_provider = FakeSheetsProvider()
    monkeypatch.setattr("app.main.get_sheets_provider_from_env", lambda: fake_provider)
    invalid_payload = {**submission_payload, field: value}

    response = TestClient(app).post("/api/submissions", json=invalid_payload)

    assert response.status_code == 422
    assert value not in response.text
    assert fake_provider.rows == []


def test_submission_api_rejects_unexpected_field_and_oversized_value(
    monkeypatch,
    submission_payload,
):
    fake_provider = FakeSheetsProvider()
    monkeypatch.setattr("app.main.get_sheets_provider_from_env", lambda: fake_provider)

    unexpected = TestClient(app).post(
        "/api/submissions", json={**submission_payload, "scanId": "not-a-sheet-column"}
    )
    oversized = TestClient(app).post(
        "/api/submissions", json={**submission_payload, "message": "x" * 10_001}
    )

    assert unexpected.status_code == 422
    assert oversized.status_code == 422
    assert fake_provider.rows == []


@pytest.mark.parametrize(
    ("error_code", "expected_status"),
    [
        ("sheets_unavailable", 503),
        ("sheet_header_mismatch", 409),
        ("sheets_api_error", 502),
    ],
)
def test_submission_api_never_reports_success_for_provider_errors(
    monkeypatch,
    submission_payload,
    error_code,
    expected_status,
):
    fake_provider = FakeSheetsProvider(error_code=error_code)
    monkeypatch.setattr("app.main.get_sheets_provider_from_env", lambda: fake_provider)

    response = TestClient(app).post("/api/submissions", json=submission_payload)

    assert response.status_code == expected_status
    assert response.json() == {"detail": {"code": error_code}}
    assert fake_provider.rows == []
