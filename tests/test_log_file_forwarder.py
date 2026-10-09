import json

import pytest

from demo.follow_server_log import validate_event_line


def test_validate_event_line_accepts_log_event() -> None:
    event = {
        "timestamp": "2026-10-08T18:30:00Z",
        "severity": "error",
        "service": "payments",
        "message": "Payment provider timed out",
        "environment": "production",
        "attributes": {"region": "west"},
    }

    assert validate_event_line(json.dumps(event).encode(), 4) == event


def test_validate_event_line_accepts_event_without_source_severity() -> None:
    event = {
        "timestamp": "2026-10-08T18:30:00Z",
        "service": "payments",
        "message": "Payment provider timed out",
    }

    assert validate_event_line(json.dumps(event).encode(), 4) == event


@pytest.mark.parametrize(
    ("line", "message"),
    [
        (b"not json", "line 2 is not a valid log event"),
        (
            b'{"timestamp":"2026-10-08T18:30:00","severity":"info",'
            b'"service":"payments","message":"missing timezone"}',
            "line 2 is not a valid log event",
        ),
        (
            b'{"timestamp":"2026-10-08T18:30:00Z","severity":"info",'
            b'"service":"payments","message":"unknown tenant",'
            b'"organization_id":"other-org"}',
            "line 2 is not a valid log event",
        ),
    ],
)
def test_validate_event_line_rejects_invalid_events(
    line: bytes,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_event_line(line, 2)
