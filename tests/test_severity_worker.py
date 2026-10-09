import asyncio

from app.config import Settings
from app.llm_severity import LocalLlmResult
from app.severity_nlp import NlpSeverityResult
from app.severity_worker import SeverityWorker


def _settings() -> Settings:
    return Settings(
        supabase_url="http://127.0.0.1:54321",
        supabase_publishable_key="test-publishable",
        supabase_secret_key="test-secret",
    )


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "message_id": 7,
        "read_count": 1,
        "log_id": "13000000-0000-4000-8000-000000000001",
        "organization_id": "12000000-0000-4000-8000-000000000001",
        "source_severity": "warning",
        "service": "checkout",
        "message": "Primary database is unavailable and all checkout requests are failing",
        "recent_similar_errors": 1,
        "previous_similar_errors": 0,
        "template_seen_before": True,
        "service_criticality": "normal",
        "escalating_sequence": False,
    }
    row.update(overrides)
    return row


class FakeWorker(SeverityWorker):
    def __init__(self, rows: list[dict[str, object]]) -> None:
        super().__init__(_settings(), None, client=None)  # type: ignore[arg-type]
        self.rows = rows
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def _rpc(self, function: str, payload: dict[str, object]):
        self.calls.append((function, payload))
        if function == "claim_log_for_severity_prediction":
            return [self.rows.pop(0)] if self.rows else []
        return None


def test_worker_uses_matching_critical_rule_without_calling_llm() -> None:
    worker = FakeWorker([_row()])

    processed = asyncio.run(worker.process_one())

    assert processed is True
    assert worker.calls[1] == (
        "finish_log_severity_prediction",
        {
            "p_message_id": 7,
            "p_log_id": "13000000-0000-4000-8000-000000000001",
            "p_status": "complete",
            "p_severity": "critical",
            "p_confidence": 0.98,
            "p_reason": (
                "A core service-wide failure is preventing essential operations."
            ),
            "p_method": "message_rule",
            "p_error": None,
        },
    )


def test_worker_sends_uncertain_case_to_llm(monkeypatch) -> None:
    async def fake_llm(**kwargs) -> LocalLlmResult:
        assert kwargs["message"] == "Unfamiliar event with no source level"
        return LocalLlmResult("warning", 0.8, "The message signals a possible risk.")

    monkeypatch.setattr("app.severity_worker.predict_with_local_llm", fake_llm)
    worker = FakeWorker(
        [
            _row(
                source_severity=None,
                message="Unfamiliar event with no source level",
                recent_similar_errors=0,
            )
        ]
    )

    processed = asyncio.run(worker.process_one())

    assert processed is True
    assert worker.calls[1][1]["p_severity"] == "warning"
    assert worker.calls[1][1]["p_method"] == "local_llm"


def test_worker_can_select_nlp_layer_result(monkeypatch) -> None:
    worker = FakeWorker(
        [
            _row(
                source_severity=None,
                message="Connection refused",
            )
        ]
    )
    worker.classifier = object()
    monkeypatch.setattr(
        "app.severity_worker.predict_with_nlp",
        lambda classifier, message: NlpSeverityResult("error", 0.96),
    )

    asyncio.run(worker.process_one())

    assert worker.calls[1][1]["p_method"] == "nlp"
    assert worker.calls[1][1]["p_severity"] == "error"


def test_worker_releases_transient_failures_for_bounded_retry() -> None:
    worker = FakeWorker(
        [
            _row(
                source_severity=None,
                message="Unfamiliar event with no source level",
            )
        ]
    )

    async def fail_llm(**kwargs) -> LocalLlmResult:
        raise RuntimeError("Ollama is not running")

    import app.severity_worker as worker_module

    original = worker_module.predict_with_local_llm
    worker_module.predict_with_local_llm = fail_llm
    try:
        asyncio.run(worker.process_one())
    finally:
        worker_module.predict_with_local_llm = original

    assert worker.calls[1] == (
        "release_log_for_severity_retry",
        {"p_message_id": 7, "p_delay_seconds": 2},
    )


def test_worker_records_transient_failure_reason_without_log_content() -> None:
    worker = FakeWorker(
        [
            _row(
                message_id=9,
                read_count=3,
                source_severity=None,
                message="Unfamiliar event with no source level",
            )
        ]
    )

    async def fail_llm(**kwargs) -> LocalLlmResult:
        raise RuntimeError("Local Ollama severity request timed out")

    import app.severity_worker as worker_module

    original = worker_module.predict_with_local_llm
    worker_module.predict_with_local_llm = fail_llm
    try:
        asyncio.run(worker.process_one())
    finally:
        worker_module.predict_with_local_llm = original

    assert worker.calls[1][0] == "finish_log_severity_prediction"
    assert worker.calls[1][1]["p_status"] == "failed"
    assert "RuntimeError" in str(worker.calls[1][1]["p_error"])
    assert "Unfamiliar event" not in str(worker.calls[1][1]["p_error"])
