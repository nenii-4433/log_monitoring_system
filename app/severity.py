from dataclasses import dataclass
import re
from typing import Literal

Severity = Literal["trace", "debug", "info", "warning", "error", "critical"]


@dataclass(frozen=True)
class SeverityRuleResult:
    severity: Severity
    confidence: float
    reason: str
    source: Literal["message_rule", "source_hint"]


_RULES: tuple[tuple[Severity, float, str, re.Pattern[str]], ...] = (
    (
        "critical",
        0.98,
        "A core service-wide failure is preventing essential operations.",
        re.compile(
            r"\b(?:primary|main)\s+(?:database|db)\s+(?:is\s+)?unavailable\b"
            r"|\ball\s+(?:\w+\s+){0,2}requests?\s+(?:are\s+)?failing\b"
            r"|\b(?:out of memory|oom)\b.*\b(?:terminating|cannot restart|unavailable)\b"
            r"|\b(?:encryption key exposure|data breach)\s+confirmed\b",
            re.IGNORECASE,
        ),
    ),
    (
        "error",
        0.9,
        "The message indicates a failed operation that needs investigation.",
        re.compile(
            r"\b(?:failed|failure|exception|timed out|timeout|connection refused"
            r"|could not|i/o error|segfault)\b|\bHTTP\s+5\d\d\b",
            re.IGNORECASE,
        ),
    ),
    (
        "warning",
        0.82,
        "The message indicates a risk or degradation, but not a confirmed total failure.",
        re.compile(
            r"\b(?:latency|response time)\b.*\b(?:threshold|normal|increased|high)\b"
            r"|\bexpires?\s+in\b|\bqueue depth\b.*\b(?:increased|reached)\b"
            r"|\bdegraded\b|\bapproaching (?:the )?(?:limit|threshold)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "trace",
        0.84,
        "The message describes a fine-grained execution or tracing detail.",
        re.compile(
            r"\b(?:entering|leaving) (?:the )?(?:function|method|retry loop)\b"
            r"|\b(?:trace|span) id\b|\bselected route\b",
            re.IGNORECASE,
        ),
    ),
    (
        "debug",
        0.8,
        "The message contains internal diagnostic state or configuration.",
        re.compile(
            r"\b(?:configured with|connection pool|feature flag|cache lookup"
            r"|resolved to|parsed request)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "info",
        0.78,
        "The message describes expected or successful application behavior.",
        re.compile(
            r"\b(?:completed successfully|successfully|returned HTTP 2\d\d"
            r"|session created)\b",
            re.IGNORECASE,
        ),
    ),
)

_ALLOWED_SEVERITIES = frozenset(
    {"trace", "debug", "info", "warning", "error", "critical"}
)


def predict_severity_from_rules(
    message: str,
    source_severity: str | None = None,
) -> SeverityRuleResult | None:
    """Apply deterministic message rules, using a producer label only as fallback."""
    normalized_message = message.strip()
    if not normalized_message:
        raise ValueError("message must not be blank")

    for severity, confidence, reason, pattern in _RULES:
        if pattern.search(normalized_message):
            return SeverityRuleResult(
                severity=severity,
                confidence=confidence,
                reason=reason,
                source="message_rule",
            )

    if source_severity in _ALLOWED_SEVERITIES:
        return SeverityRuleResult(
            severity=source_severity,
            confidence=0.55,
            reason="No message rule matched; using the producer severity as a weak hint.",
            source="source_hint",
        )

    return None
