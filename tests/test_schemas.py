import pytest
from pydantic import ValidationError

from app.schemas import LogEvent


def test_accepts_valid_log_event() -> None:
    event = LogEvent.model_validate(
        {
            "timestamp": "2026-10-08T09:30:00Z",
            "severity": "error",
            "service": "checkout",
            "message": "Payment provider timed out",
            "environment": "production",
            "attributes": {"region": "west"},
        }
    )

    assert event.severity == "error"
    assert event.timestamp.utcoffset() is not None


def test_rejects_timestamp_without_timezone() -> None:
    with pytest.raises(ValidationError):
        LogEvent.model_validate(
            {
                "timestamp": "2026-10-08T09:30:00",
                "severity": "error",
                "service": "checkout",
                "message": "Payment provider timed out",
            }
        )


def test_rejects_unknown_organization_field() -> None:
    with pytest.raises(ValidationError):
        LogEvent.model_validate(
            {
                "timestamp": "2026-10-08T09:30:00Z",
                "severity": "error",
                "service": "checkout",
                "message": "Payment provider timed out",
                "organization_id": "another-tenant",
            }
        )


def test_rejects_invalid_severity() -> None:
    with pytest.raises(ValidationError):
        LogEvent.model_validate(
            {
                "timestamp": "2026-10-08T09:30:00Z",
                "severity": "urgent",
                "service": "checkout",
                "message": "Payment provider timed out",
            }
        )


def test_rejects_message_over_database_limit() -> None:
    with pytest.raises(ValidationError):
        LogEvent.model_validate(
            {
                "timestamp": "2026-10-08T09:30:00Z",
                "severity": "error",
                "service": "checkout",
                "message": "x" * 262_145,
            }
        )