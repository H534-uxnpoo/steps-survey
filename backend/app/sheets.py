"""Phase 7 Google Sheets append provider.

This module deliberately has no logging and never persists submission data.
The Google client is imported only when Sheets is explicitly enabled so normal
development and fake-provider tests do not require credentials or network
access.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Mapping, Protocol, Sequence

from .models import SHEET_HEADERS

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
DEFAULT_SHEETS_RANGE = "アンケート!A:K"


class SheetsError(RuntimeError):
    """A safe, non-PII error code suitable for an API response.

    The exception message is intentionally only its stable code.  In
    particular, it must never include a Google response, row values, or the
    configured spreadsheet identifier.
    """

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SheetsProvider(Protocol):
    """Append exactly one already-confirmed, 11-cell submission row."""

    def append_row(self, row: Sequence[str]) -> None: ...


@dataclass(frozen=True)
class SheetsConfig:
    """Backend-only configuration read from environment variables."""

    enabled: bool
    spreadsheet_id: str
    range: str

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> "SheetsConfig":
        source = os.environ if environment is None else environment
        return cls(
            enabled=source.get("SHEETS_ENABLED", "").strip().lower() == "true",
            spreadsheet_id=source.get("SHEETS_SPREADSHEET_ID", "").strip(),
            range=source.get("SHEETS_RANGE", DEFAULT_SHEETS_RANGE).strip(),
        )


class UnavailableSheetsProvider:
    """Safe no-op replacement used when Sheets cannot be used.

    It deliberately raises instead of returning success, so an unconfigured
    deployment can never look as if personal data was registered.
    """

    def __init__(self, error_code: str) -> None:
        self._error_code = error_code

    def append_row(self, row: Sequence[str]) -> None:
        # Do not inspect, serialize, or log row values in the unavailable path.
        raise SheetsError(self._error_code)


class GoogleSheetsProvider:
    """Google Sheets values.append implementation using Application Default Credentials."""

    def __init__(self, config: SheetsConfig, service: Any) -> None:
        _validate_config(config)
        self._config = config
        self._service = service
        self._header_range = _header_range_for(config.range)

    def append_row(self, row: Sequence[str]) -> None:
        values = _validated_row(row)
        self._ensure_expected_header()

        try:
            # Do not request updated values in the response: row values may
            # contain personal data and are not needed after a successful append.
            (
                self._service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=self._config.spreadsheet_id,
                    range=self._config.range,
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": [values]},
                )
                .execute()
            )
        except SheetsError:
            raise
        except Exception as error:
            raise SheetsError(_request_error_code(error)) from error

    def _ensure_expected_header(self) -> None:
        try:
            response = (
                self._service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=self._config.spreadsheet_id,
                    range=self._header_range,
                )
                .execute()
            )
        except Exception as error:
            raise SheetsError(_request_error_code(error)) from error

        values = response.get("values", []) if isinstance(response, Mapping) else []
        if values != [list(SHEET_HEADERS)]:
            # Never append when the columns cannot be proven to be the expected
            # fixed A:K layout.
            raise SheetsError("sheet_header_mismatch")


def get_sheets_provider_from_env() -> SheetsProvider:
    """Return a provider that fails safely if configuration or ADC is unavailable."""

    config = SheetsConfig.from_environment()
    if not config.enabled:
        return UnavailableSheetsProvider("sheets_unavailable")

    try:
        _validate_config(config)
    except SheetsError:
        # Configuration is backend-only.  Do not reveal whether it is missing
        # an ID or has an invalid range to a browser client.
        return UnavailableSheetsProvider("sheets_unavailable")

    try:
        # `google.auth.default` supports local `gcloud auth application-default
        # login`, GOOGLE_APPLICATION_CREDENTIALS, and Cloud Run service accounts.
        from google.auth import default
        from googleapiclient.discovery import build
    except ImportError:
        return UnavailableSheetsProvider("sheets_unavailable")

    try:
        credentials, _ = default(scopes=[SHEETS_SCOPE])
        service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    except Exception:
        return UnavailableSheetsProvider("sheets_unavailable")

    return GoogleSheetsProvider(config, service)


def _validate_config(config: SheetsConfig) -> None:
    if not config.enabled:
        raise SheetsError("sheets_unavailable")
    if not config.spreadsheet_id:
        raise SheetsError("sheets_configuration_invalid")
    _header_range_for(config.range)


def _header_range_for(target_range: str) -> str:
    """Require an explicit A:K target so the fixed layout cannot drift."""

    if target_range.count("!") != 1:
        raise SheetsError("sheets_configuration_invalid")
    sheet_name, columns = target_range.split("!", maxsplit=1)
    if not sheet_name.strip() or columns != "A:K":
        raise SheetsError("sheets_configuration_invalid")
    return f"{sheet_name}!A1:K1"


def _validated_row(row: Sequence[str]) -> list[str]:
    values = list(row)
    if len(values) != len(SHEET_HEADERS) or any(not isinstance(value, str) for value in values):
        raise SheetsError("sheets_row_invalid")
    return values


def _request_error_code(error: Exception) -> str:
    """Classify credential failures without exposing provider response text."""

    response = getattr(error, "resp", None)
    status = getattr(response, "status", None)
    if status in {401, 403}:
        return "sheets_unavailable"
    return "sheets_api_error"
