import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

Severity = Literal["trace", "debug", "info", "warning", "error", "critical"]
SEVERITIES: tuple[Severity, ...] = (
    "trace",
    "debug",
    "info",
    "warning",
    "error",
    "critical",
)
_UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_TIMESTAMP_PATTERN = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b",
    re.IGNORECASE,
)
_NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\b")


@dataclass(frozen=True)
class LabeledExample:
    message: str
    label: Severity


@dataclass(frozen=True)
class NlpSeverityResult:
    severity: Severity
    confidence: float


def normalize_log_message(message: str) -> str:
    """Reduce variable IDs while preserving HTTP status codes and message meaning."""
    normalized = _TIMESTAMP_PATTERN.sub(" <timestamp> ", message)
    normalized = _UUID_PATTERN.sub(" <id> ", normalized)
    normalized = _IP_PATTERN.sub(" <ip> ", normalized)

    def replace_number(match: re.Match[str]) -> str:
        prefix = normalized[max(0, match.start() - 5) : match.start()]
        if prefix.lower() == "http ":
            return match.group()
        return " <number> "

    return _NUMBER_PATTERN.sub(replace_number, normalized).lower().strip()


def load_approved_examples(path: Path) -> list[LabeledExample]:
    examples: list[LabeledExample] = []
    with path.open(encoding="utf-8") as dataset:
        for line_number, raw_line in enumerate(dataset, start=1):
            if not raw_line.strip():
                continue
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"line {line_number} is not valid JSON"
                ) from error

            if not isinstance(row, dict):
                raise ValueError(f"line {line_number} must contain a JSON object")
            if row.get("review_status") not in {"draft", "approved"}:
                raise ValueError(
                    f"line {line_number} has an invalid review_status"
                )
            message = row.get("message")
            label = row.get("label")
            if not isinstance(message, str) or not message.strip():
                raise ValueError(f"line {line_number} has an invalid message")
            if label not in SEVERITIES:
                raise ValueError(f"line {line_number} has an invalid label")

            if row["review_status"] == "approved":
                examples.append(LabeledExample(message=message, label=label))

    return examples


def train_severity_classifier(examples: list[LabeledExample]) -> Pipeline:
    counts = {severity: 0 for severity in SEVERITIES}
    for example in examples:
        if example.label not in counts:
            raise ValueError(f"unsupported severity label: {example.label}")
        counts[example.label] += 1

    insufficient = [
        f"{severity}={count}"
        for severity, count in counts.items()
        if count < 2
    ]
    if insufficient:
        raise ValueError(
            "At least two approved examples are required for every severity; "
            f"current counts: {', '.join(insufficient)}"
        )

    classifier = Pipeline(
        steps=[
            (
                "tfidf",
                TfidfVectorizer(
                    ngram_range=(1, 2),
                    preprocessor=normalize_log_message,
                    sublinear_tf=True,
                ),
            ),
            (
                "classifier",
                LogisticRegression(
                    class_weight="balanced",
                    max_iter=1000,
                    random_state=42,
                ),
            ),
        ]
    )
    classifier.fit(
        [example.message for example in examples],
        [example.label for example in examples],
    )
    return classifier


def predict_with_nlp(
    classifier: Pipeline,
    message: str,
) -> NlpSeverityResult:
    if not message.strip():
        raise ValueError("message must not be blank")

    probabilities = classifier.predict_proba([message])[0]
    predicted_index = int(probabilities.argmax())
    severity = classifier.classes_[predicted_index]
    if severity not in SEVERITIES:
        raise ValueError(f"classifier returned an unsupported label: {severity}")

    return NlpSeverityResult(
        severity=severity,
        confidence=float(probabilities[predicted_index]),
    )
