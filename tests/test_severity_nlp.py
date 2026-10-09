import json

import pytest

from app.severity_nlp import (
    LabeledExample,
    load_approved_examples,
    normalize_log_message,
    predict_with_nlp,
    train_severity_classifier,
)


def _balanced_examples() -> list[LabeledExample]:
    examples: list[LabeledExample] = []
    for label in ("trace", "debug", "info", "warning", "error", "critical"):
        examples.extend(
            [
                LabeledExample(f"{label} diagnostic sample alpha", label),
                LabeledExample(f"{label} diagnostic sample beta", label),
            ]
        )
    return examples


def test_load_approved_examples_excludes_drafts(tmp_path) -> None:
    path = tmp_path / "examples.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "message": "approved event",
                        "label": "info",
                        "review_status": "approved",
                    }
                ),
                json.dumps(
                    {
                        "message": "draft event",
                        "label": "error",
                        "review_status": "draft",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    assert load_approved_examples(path) == [
        LabeledExample(message="approved event", label="info")
    ]


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (
            "Connection to 10.0.0.5 failed for request 128",
            "Connection to 10.0.0.9 failed for request 947",
        ),
        (
            "Request 2026-10-09T21:15:00Z failed with id "
            "123e4567-e89b-12d3-a456-426614174000",
            "Request 2026-10-10T21:15:00Z failed with id "
            "123e4567-e89b-12d3-a456-426614174001",
        ),
    ],
)
def test_normalize_log_message_reduces_variable_values(
    left: str,
    right: str,
) -> None:
    assert normalize_log_message(left) == normalize_log_message(right)


def test_normalize_log_message_preserves_http_status_code() -> None:
    assert "http 503" in normalize_log_message("Request returned HTTP 503")


def test_train_requires_at_least_two_approved_examples_per_label() -> None:
    with pytest.raises(ValueError, match="At least two approved examples"):
        train_severity_classifier(
            [LabeledExample("one sample", "critical")]
        )


def test_classifier_predicts_from_trained_examples() -> None:
    classifier = train_severity_classifier(_balanced_examples())

    result = predict_with_nlp(classifier, "error diagnostic sample alpha")

    assert result.severity == "error"
    assert 0.0 <= result.confidence <= 1.0


def test_predict_rejects_blank_message() -> None:
    classifier = train_severity_classifier(_balanced_examples())

    with pytest.raises(ValueError, match="message must not be blank"):
        predict_with_nlp(classifier, " ")
