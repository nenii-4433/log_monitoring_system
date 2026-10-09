from dataclasses import dataclass
from typing import Literal

ServiceCriticality = Literal["low", "normal", "high", "critical"]


@dataclass(frozen=True)
class ContextSnapshot:
    recent_similar_errors: int
    previous_similar_errors: int
    template_seen_before: bool
    service_criticality: ServiceCriticality
    escalating_sequence: bool = False


@dataclass(frozen=True)
class ContextAssessment:
    spike_detected: bool
    new_template: bool
    important_service: bool
    escalating_sequence: bool
    llm_recommended: bool
    reasons: tuple[str, ...]


def assess_severity_context(snapshot: ContextSnapshot) -> ContextAssessment:
    """Summarize organization-scoped context for the later prediction worker."""
    if snapshot.recent_similar_errors < 0 or snapshot.previous_similar_errors < 0:
        raise ValueError("error counts must not be negative")

    spike_detected = (
        snapshot.recent_similar_errors >= 5
        and snapshot.recent_similar_errors
        >= 3 * max(snapshot.previous_similar_errors, 1)
    )
    new_template = not snapshot.template_seen_before
    important_service = snapshot.service_criticality in {"high", "critical"}

    reasons: list[str] = []
    if spike_detected:
        reasons.append(
            "At least five similar errors occurred, at three times or more "
            "the count in the previous five-minute window."
        )
    if new_template:
        reasons.append("This log template has not been seen before.")
    if important_service:
        reasons.append(
            f"The service is marked {snapshot.service_criticality} criticality "
            "for this organization."
        )
    if snapshot.escalating_sequence:
        reasons.append(
            "Recent events from this service indicate an escalating sequence."
        )

    llm_recommended = (
        spike_detected
        or snapshot.escalating_sequence
        or (
            important_service
            and (
                snapshot.recent_similar_errors > 0
                or new_template
            )
        )
    )

    return ContextAssessment(
        spike_detected=spike_detected,
        new_template=new_template,
        important_service=important_service,
        escalating_sequence=snapshot.escalating_sequence,
        llm_recommended=llm_recommended,
        reasons=tuple(reasons),
    )
