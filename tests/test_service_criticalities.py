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


def test_list_service_criticalities_returns_organization_settings(monkeypatch) -> None:
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> list[dict[str, str]]:
            return [{"service": "payments", "criticality": "high"}]

    class FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            assert timeout == 5.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, headers: dict, json: dict) -> FakeResponse:
            assert url.endswith("/rpc/get_service_criticalities")
            assert json["p_user_id"] == "verified-user-123"
            assert json["p_organization_id"] == (
                "12000000-0000-4000-8000-000000000001"
            )
            return FakeResponse()

    monkeypatch.setattr(main.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(main, "get_settings", _settings)
    main.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="verified-user-123"
    )
    try:
        with TestClient(main.app) as client:
            response = client.get(
                "/v1/organizations/"
                "12000000-0000-4000-8000-000000000001/service-criticalities"
            )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "items": [{"service": "payments", "criticality": "high"}]
    }


def test_owner_can_set_service_criticality(monkeypatch) -> None:
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> list[dict[str, str]]:
            return [
                {
                    "service": "payments",
                    "criticality": "critical",
                    "updated_at": "2026-10-09T12:00:00+00:00",
                }
            ]

    class FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, headers: dict, json: dict) -> FakeResponse:
            assert url.endswith("/rpc/set_service_criticality")
            assert json["p_user_id"] == "verified-user-123"
            assert json["p_service"] == "payments"
            assert json["p_criticality"] == "critical"
            return FakeResponse()

    monkeypatch.setattr(main.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(main, "get_settings", _settings)
    main.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="verified-user-123"
    )
    try:
        with TestClient(main.app) as client:
            response = client.put(
                "/v1/organizations/"
                "12000000-0000-4000-8000-000000000001/service-criticalities",
                json={"service": " payments ", "criticality": "critical"},
            )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "service": "payments",
        "criticality": "critical",
        "updated_at": "2026-10-09T12:00:00+00:00",
    }


def test_service_criticality_rejects_invalid_values() -> None:
    main.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="verified-user-123"
    )
    try:
        with TestClient(main.app) as client:
            response = client.put(
                "/v1/organizations/"
                "12000000-0000-4000-8000-000000000001/service-criticalities",
                json={"service": "payments", "criticality": "urgent"},
            )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 422
