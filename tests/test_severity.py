import pytest

from app.severity import predict_severity_from_rules


@pytest.mark.parametrize(
    ("message", "source_severity", "expected"),
    [
        (
            "Primary database is unavailable and all checkout requests are failing",
            "warning",
            ("critical", "message_rule"),
        ),
        (
            "Out of memory; process is terminating and cannot restart",
            None,
            ("critical", "message_rule"),
        ),
        (
            "Payment authorization failed: provider returned HTTP 503",
            None,
            ("error", "message_rule"),
        ),
        (
            "Database query failed after retries",
            "info",
            ("error", "message_rule"),
        ),
        (
            "Certificate expires in 5 days; renewal has not completed",
            None,
            ("warning", "message_rule"),
        ),
        (
            "Parsed request header and selected route /health",
            None,
            ("trace", "message_rule"),
        ),
        (
            "Connection pool currently has 3 idle connections",
            None,
            ("debug", "message_rule"),
        ),
        (
            "User session created successfully",
            None,
            ("info", "message_rule"),
        ),
        (
            "An unfamiliar message",
            "error",
            ("error", "source_hint"),
        ),
    ],
)
def test_predicts_severity_from_rules(
    message: str,
    source_severity: str | None,
    expected: tuple[str, str],
) -> None:
    result = predict_severity_from_rules(message, source_severity)

    assert result is not None
    assert (result.severity, result.source) == expected
    assert 0.0 <= result.confidence <= 1.0
    assert result.reason


def test_returns_none_when_no_message_rule_or_source_hint_matches() -> None:
    assert predict_severity_from_rules("An unfamiliar message") is None


def test_rejects_blank_message() -> None:
    with pytest.raises(ValueError, match="message must not be blank"):
        predict_severity_from_rules("   ")


def test_ignores_invalid_source_severity() -> None:
    assert predict_severity_from_rules("An unfamiliar message", "urgent") is None
