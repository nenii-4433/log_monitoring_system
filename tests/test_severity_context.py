import pytest

from app.severity_context import ContextSnapshot, assess_severity_context


def _snapshot(**overrides: object) -> ContextSnapshot:
    values: dict[str, object] = {
        "recent_similar_errors": 0,
        "previous_similar_errors": 0,
        "template_seen_before": True,
        "service_criticality": "normal",
    }
    values.update(overrides)
    return ContextSnapshot(**values)


def test_detects_at_least_five_errors_at_three_times_previous_window() -> None:
    result = assess_severity_context(
        _snapshot(recent_similar_errors=15, previous_similar_errors=5)
    )

    assert result.spike_detected is True
    assert result.llm_recommended is True


@pytest.mark.parametrize(
    ("recent", "previous"),
    [
        (4, 0),
        (14, 5),
        (5, 2),
    ],
)
def test_does_not_detect_spike_below_starter_threshold(
    recent: int,
    previous: int,
) -> None:
    result = assess_severity_context(
        _snapshot(
            recent_similar_errors=recent,
            previous_similar_errors=previous,
        )
    )

    assert result.spike_detected is False
    assert result.llm_recommended is False


def test_first_five_similar_errors_can_trigger_spike_without_history() -> None:
    result = assess_severity_context(
        _snapshot(recent_similar_errors=5, previous_similar_errors=0)
    )

    assert result.spike_detected is True


@pytest.mark.parametrize("criticality", ["high", "critical"])
def test_important_service_recommends_llm_for_an_error(
    criticality: str,
) -> None:
    result = assess_severity_context(
        _snapshot(
            recent_similar_errors=1,
            service_criticality=criticality,
        )
    )

    assert result.important_service is True
    assert result.llm_recommended is True


def test_new_template_is_reported_but_does_not_alone_call_llm() -> None:
    result = assess_severity_context(
        _snapshot(template_seen_before=False)
    )

    assert result.new_template is True
    assert result.llm_recommended is False


def test_escalating_sequence_recommends_llm() -> None:
    result = assess_severity_context(_snapshot(escalating_sequence=True))

    assert result.escalating_sequence is True
    assert result.llm_recommended is True


def test_rejects_negative_error_counts() -> None:
    with pytest.raises(ValueError, match="error counts must not be negative"):
        assess_severity_context(
            _snapshot(recent_similar_errors=-1)
        )
