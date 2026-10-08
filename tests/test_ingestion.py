import hashlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.config import Settings


def test_ingest_log_sends_hashed_key_and_returns_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_key = "lm_this-is-a-long-test-api-key"
    captured_payload: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> list[dict[str, str]]:
            return [
                {
                    "id": "log-123",
                    "accepted_at": "2026-10-08T09:30:01+00:00",
                }
            ]

    class FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            assert timeout == 5.0

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            headers: dict[str, str],
            json: dict[str, object],
        ) -> FakeResponse:
            assert url.endswith("/rest/v1/rpc/ingest_log_for_api_key")
            assert headers["apikey"] == "test-secret"
            assert headers["Authorization"] == "Bearer test-secret"
            captured_payload.update(json)
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(
            supabase_url="http://127.0.0.1:54321",
            supabase_publishable_key="test-publishable",
            supabase_secret_key="test-secret",
        ),
    )

    event = {
        "timestamp": "2026-10-08T09:30:00Z",
        "severity": "error",
        "service": "checkout",
        "message": "Payment provider timed out",
        "environment": "production",
        "attributes": {"region": "west"},
    }
    with TestClient(main.app) as client:
        response = client.post(
            "/v1/logs",
            headers={"Authorization": f"Bearer {api_key}"},
            json=event,
        )

    assert response.status_code == 202
    assert response.json() == {
        "id": "log-123",
        "accepted_at": "2026-10-08T09:30:01+00:00",
    }
    assert captured_payload["p_key_prefix"] == api_key[:15]
    assert captured_payload["p_secret_hash"] == hashlib.sha256(
        api_key.encode("utf-8")
    ).hexdigest()
    assert captured_payload["p_severity"] == "error"
    assert captured_payload["p_service"] == "checkout"
    assert captured_payload["p_message"] == "Payment provider timed out"
    assert captured_payload["p_attributes"] == {"region": "west"}
    assert "p_organization_id" not in captured_payload
    assert api_key not in json.dumps(captured_payload)


def test_ingest_log_rejects_missing_or_malformed_api_key() -> None:
    event = {
        "timestamp": "2026-10-08T09:30:00Z",
        "severity": "error",
        "service": "checkout",
        "message": "Payment provider timed out",
    }

    with TestClient(main.app) as client:
        missing = client.post("/v1/logs", json=event)
        malformed = client.post(
            "/v1/logs",
            headers={"Authorization": "Bearer not-a-valid-key"},
            json=event,
        )

    assert missing.status_code == 401
    assert malformed.status_code == 401
    assert missing.json()["detail"] == malformed.json()["detail"]


def test_ingest_log_rejects_oversized_request_before_database_call() -> None:
    with TestClient(main.app) as client:
        response = client.post(
            "/v1/logs",
            headers={
                "Authorization": "Bearer lm_this-is-a-long-test-api-key",
                "Content-Type": "application/json",
            },
            content=b"x" * 262_145,
        )

    assert response.status_code == 413


def test_ingest_log_stops_reading_oversized_chunked_body() -> None:
    def oversized_chunks():
        yield b'{"message":"'
        yield b"x" * 262_145

    with TestClient(main.app) as client:
        response = client.post(
            "/v1/logs",
            headers={
                "Authorization": "Bearer lm_this-is-a-long-test-api-key",
                "Content-Type": "application/json",
                "Transfer-Encoding": "chunked",
            },
            content=oversized_chunks(),
        )

    assert response.status_code == 413


def test_ingest_log_rejects_invalid_event_before_database_call() -> None:
    event = {
        "timestamp": "2026-10-08T09:30:00",
        "severity": "error",
        "service": "checkout",
        "message": "Payment provider timed out",
        "organization_id": "attacker-selected-org",
    }

    with TestClient(main.app) as client:
        response = client.post(
            "/v1/logs",
            headers={"Authorization": "Bearer lm_this-is-a-long-test-api-key"},
            json=event,
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid log event"


def test_ingest_log_maps_invalid_database_key_to_unauthorized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status_code = 401

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
            headers: dict[str, str],
            json: dict[str, object],
        ) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(
            supabase_url="http://127.0.0.1:54321",
            supabase_publishable_key="test-publishable",
            supabase_secret_key="test-secret",
        ),
    )

    with TestClient(main.app) as client:
        response = client.post(
            "/v1/logs",
            headers={"Authorization": "Bearer lm_this-is-a-long-test-api-key"},
            json={
                "timestamp": "2026-10-08T09:30:00Z",
                "severity": "error",
                "service": "checkout",
                "message": "Payment provider timed out",
            },
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"


def test_openapi_documents_log_event_request_body() -> None:
    with TestClient(main.app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    operation = response.json()["paths"]["/v1/logs"]["post"]
    body_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert body_schema["additionalProperties"] is False
    assert set(body_schema["required"]) == {
        "timestamp",
        "severity",
        "service",
        "message",
    }
