import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.auth import AuthenticatedUser, get_current_user
from app.config import Settings


def _settings() -> Settings:
    return Settings(
        supabase_url="http://127.0.0.1:54321",
        supabase_publishable_key="test-publishable",
        supabase_secret_key="test-secret",
    )


def test_search_logs_filters_and_encodes_next_page_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_payload: dict[str, object] = {}
    first_id = "13000000-0000-4000-8000-000000000001"
    second_id = "13000000-0000-4000-8000-000000000002"

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> list[dict[str, object]]:
            return [
                {
                    "id": first_id,
                    "event_timestamp": "2026-10-08T11:00:00+00:00",
                    "received_at": "2026-10-08T11:00:01+00:00",
                    "severity": None,
                    "source_severity": "warning",
                    "prediction_status": "complete",
                    "prediction_confidence": 0.9,
                    "prediction_reason": "The operation failed.",
                    "prediction_error": None,
                    "prediction_method": "rule",
                    "service": "checkout",
                    "environment": "production",
                    "message": "Payment provider timed out",
                    "attributes": {"region": "west"},
                },
                {
                    "id": second_id,
                    "event_timestamp": "2026-10-08T10:00:00+00:00",
                    "received_at": "2026-10-08T10:00:01+00:00",
                    "severity": None,
                    "source_severity": None,
                    "prediction_status": "pending",
                    "prediction_confidence": None,
                    "prediction_reason": None,
                    "prediction_method": None,
                    "prediction_error": None,
                    "service": "checkout",
                    "environment": "production",
                    "message": "Retrying payment",
                    "attributes": None,
                },
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
            assert url.endswith("/rest/v1/rpc/search_logs_for_member")
            assert headers["apikey"] == "test-secret"
            captured_payload.update(json)
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(main, "get_settings", _settings)
    main.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="verified-user-123"
    )

    try:
        with TestClient(main.app) as client:
            response = client.get(
                "/v1/logs",
                params=[
                    ("organization_id", "12000000-0000-4000-8000-000000000001"),
                    ("from", "2026-10-08T09:00:00Z"),
                    ("to", "2026-10-08T12:00:00Z"),
                    ("severity", "error"),
                    ("severity", "warning"),
                    ("service", "checkout"),
                    ("environment", "production"),
                    ("limit", "1"),
                ],
            )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == [
        {
            "id": first_id,
            "timestamp": "2026-10-08T11:00:00+00:00",
            "received_at": "2026-10-08T11:00:01+00:00",
            "severity": None,
            "source_severity": "warning",
            "prediction_status": "complete",
            "prediction_confidence": 0.9,
            "prediction_reason": "The operation failed.",
            "prediction_method": "rule",
            "prediction_error": None,
            "service": "checkout",
            "environment": "production",
            "message": "Payment provider timed out",
            "attributes": {"region": "west"},
        }
    ]
    cursor_bytes = base64.urlsafe_b64decode(
        body["next_cursor"] + "=" * (-len(body["next_cursor"]) % 4)
    )
    assert json.loads(cursor_bytes) == {
        "timestamp": "2026-10-08T11:00:00+00:00",
        "id": first_id,
    }
    assert captured_payload["p_user_id"] == "verified-user-123"
    assert captured_payload["p_organization_id"] == (
        "12000000-0000-4000-8000-000000000001"
    )
    assert captured_payload["p_from"] == "2026-10-08T09:00:00+00:00"
    assert captured_payload["p_to"] == "2026-10-08T12:00:00+00:00"
    assert captured_payload["p_severities"] == ["error", "warning"]
    assert captured_payload["p_service"] == "checkout"
    assert captured_payload["p_environment"] == "production"
    assert captured_payload["p_limit"] == 2


@pytest.mark.parametrize(
    ("params", "expected_detail"),
    [
        ({"severity": "urgent"}, "Invalid severity filter"),
        (
            {
                "from": "2026-10-08T12:00:00Z",
                "to": "2026-10-08T11:00:00Z",
            },
            "from must be earlier than or equal to to",
        ),
        ({"cursor": "not-a-valid-cursor"}, "Invalid pagination cursor"),
        (
            {"cursor": base64.urlsafe_b64encode(b"[]").decode().rstrip("=")},
            "Invalid pagination cursor",
        ),
    ],
)
def test_search_logs_rejects_invalid_filters_and_cursors(
    params: dict[str, str],
    expected_detail: str,
) -> None:
    query = {
        "organization_id": "12000000-0000-4000-8000-000000000001",
        **params,
    }
    main.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="verified-user-123"
    )

    try:
        with TestClient(main.app) as client:
            response = client.get("/v1/logs", params=query)
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == expected_detail


def test_search_logs_hides_inaccessible_organization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status_code = 403

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
    monkeypatch.setattr(main, "get_settings", _settings)
    main.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="verified-user-123"
    )

    try:
        with TestClient(main.app) as client:
            response = client.get(
                "/v1/logs",
                params={
                    "organization_id": (
                        "12000000-0000-4000-8000-000000000002"
                    )
                },
            )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Organization not found"
