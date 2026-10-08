from fastapi.testclient import TestClient

import app.main as main
from app.auth import AuthenticatedUser, get_current_user
from app.config import Settings


def test_create_organization_uses_verified_user_and_secret_key(
    monkeypatch,
) -> None:
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> list[dict[str, str]]:
            return [
                {
                    "id": "org-123",
                    "name": "Example Company",
                    "role": "owner",
                    "created_at": "2026-10-08T00:00:00Z",
                }
            ]

    class FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            assert timeout == 5.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, headers: dict, json: dict):
            assert url.endswith(
                "/rest/v1/rpc/create_organization_for_user"
            )
            assert headers["apikey"] == "test-secret"
            assert headers["Authorization"] == "Bearer test-secret"
            assert json == {
                "p_user_id": "verified-user-123",
                "p_name": "Example Company",
            }
            return FakeResponse()

    monkeypatch.setattr(main.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(
            supabase_url="http://127.0.0.1:54321",
            supabase_publishable_key="test-publishable",
            supabase_secret_key="test-secret",
        ),
    )
    main.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="verified-user-123"
    )

    try:
        with TestClient(main.app) as client:
            response = client.post(
                "/v1/organizations",
                json={"name": "Example Company"},
            )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json() == {
        "id": "org-123",
        "name": "Example Company",
        "role": "owner",
        "created_at": "2026-10-08T00:00:00Z",
    }


def test_create_organization_rejects_client_supplied_user_id() -> None:
    main.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="verified-user-123"
    )

    try:
        with TestClient(main.app) as client:
            response = client.post(
                "/v1/organizations",
                json={
                    "name": "Example Company",
                    "user_id": "attacker-selected-user",
                },
            )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 422


def test_create_organization_rejects_blank_name() -> None:
    main.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="verified-user-123"
    )

    try:
        with TestClient(main.app) as client:
            response = client.post(
                "/v1/organizations",
                json={"name": "   "},
            )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 422

def test_list_organizations_filters_by_verified_user(
    monkeypatch,
) -> None:
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> list[dict]:
            return [
                {
                    "role": "owner",
                    "organization": {
                        "id": "org-123",
                        "name": "Example Company",
                    },
                }
            ]

    class FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            assert timeout == 5.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(
            self,
            url: str,
            headers: dict,
            params: dict,
        ) -> FakeResponse:
            assert url.endswith("/rest/v1/organization_members")
            assert headers["apikey"] == "test-secret"
            assert params["user_id"] == "eq.verified-user-123"
            assert params["select"] == "role,organization:organizations(id,name)"
            return FakeResponse()

    monkeypatch.setattr(main.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(
            supabase_url="http://127.0.0.1:54321",
            supabase_publishable_key="test-publishable",
            supabase_secret_key="test-secret",
        ),
    )
    main.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="verified-user-123"
    )

    try:
        with TestClient(main.app) as client:
            response = client.get("/v1/organizations")
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": "org-123",
                "name": "Example Company",
                "role": "owner",
            }
        ]
    }