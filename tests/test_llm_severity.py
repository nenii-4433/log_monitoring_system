import asyncio
import json

import httpx
import pytest

from app.llm_severity import (
    LayerDecision,
    _require_loopback_url,
    predict_with_local_llm,
    should_use_llm_fallback,
)
from app.severity_context import ContextAssessment
from app.severity_nlp import NlpSeverityResult


def _context(**overrides: object) -> ContextAssessment:
    values: dict[str, object] = {
        "spike_detected": False,
        "new_template": False,
        "important_service": False,
        "escalating_sequence": False,
        "llm_recommended": False,
        "reasons": (),
    }
    values.update(overrides)
    return ContextAssessment(**values)


def test_llm_gate_skips_agreeing_high_confidence_layers() -> None:
    assert not should_use_llm_fallback(
        [
            LayerDecision("error", 0.9, "rule"),
            LayerDecision("error", 0.85, "nlp"),
        ],
        _context(),
    )


def test_llm_gate_triggers_when_layers_disagree() -> None:
    assert should_use_llm_fallback(
        [
            LayerDecision("warning", 0.9, "rule"),
            LayerDecision("error", 0.85, "nlp"),
        ],
        _context(),
    )


def test_llm_gate_triggers_for_low_confidence_or_context() -> None:
    assert should_use_llm_fallback(
        [LayerDecision("warning", 0.5, "rule")],
        _context(),
    )
    assert should_use_llm_fallback(
        [LayerDecision("warning", 0.9, "rule")],
        _context(llm_recommended=True),
    )


def test_llm_gate_triggers_when_no_layers_have_a_decision() -> None:
    assert should_use_llm_fallback([], _context())


@pytest.mark.parametrize("threshold", [-0.1, 1.1])
def test_llm_gate_rejects_invalid_confidence_threshold(threshold: float) -> None:
    with pytest.raises(ValueError, match="confidence_threshold"):
        should_use_llm_fallback([], _context(), threshold)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:11434",
        "http://192.168.1.10:11434",
        "http://user:pass@localhost:11434",
    ],
)
def test_only_accepts_local_ollama_endpoint(url: str) -> None:
    with pytest.raises(ValueError):
        _require_loopback_url(url)


@pytest.mark.parametrize("url", ["http://localhost:11434", "http://[::1]:11434"])
def test_accepts_loopback_ollama_endpoint(url: str) -> None:
    assert _require_loopback_url(url) == url


def test_local_llm_uses_json_schema_and_parses_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        @staticmethod
        def json() -> dict[str, str]:
            return {
                "response": json.dumps(
                    {
                        "severity": "critical",
                        "confidence": 0.91,
                        "reason": "The primary database is unavailable.",
                    }
                )
            }

        @staticmethod
        def raise_for_status() -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            assert timeout == 120.0

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            json: dict[str, object],
        ) -> FakeResponse:
            captured["url"] = url
            captured.update(json)
            return FakeResponse()

    monkeypatch.setattr("app.llm_severity.httpx.AsyncClient", FakeAsyncClient)
    result = asyncio.run(
        predict_with_local_llm(
            "Primary database is unavailable",
            "checkout",
            "warning",
            LayerDecision("critical", 0.98, "message_rule"),
            NlpSeverityResult("error", 0.61),
            _context(spike_detected=True, llm_recommended=True),
        )
    )

    assert captured["url"] == "http://127.0.0.1:11434/api/generate"
    assert captured["model"] == "qwen3:4b"
    assert captured["think"] is False
    assert captured["options"] == {"temperature": 0, "num_predict": 384}
    assert isinstance(captured["format"], dict)
    assert result.severity == "critical"
    assert result.confidence == 0.91


def test_local_llm_rejects_invalid_structured_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        @staticmethod
        def json() -> dict[str, str]:
            return {"response": '{"severity":"urgent","confidence":2,"reason":""}'}

        @staticmethod
        def raise_for_status() -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            json: dict[str, object],
        ) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr("app.llm_severity.httpx.AsyncClient", FakeAsyncClient)
    with pytest.raises(RuntimeError, match="invalid severity result"):
        asyncio.run(
            predict_with_local_llm(
                "message",
                "service",
                None,
                None,
                None,
                _context(),
            )
        )


def test_local_llm_reports_connection_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            json: dict[str, object],
        ) -> None:
            raise httpx.ConnectError("not running")

    monkeypatch.setattr("app.llm_severity.httpx.AsyncClient", FakeAsyncClient)
    with pytest.raises(RuntimeError, match="Local Ollama request failed"):
        asyncio.run(
            predict_with_local_llm(
                "message",
                "service",
                None,
                None,
                None,
                _context(),
            )
        )
