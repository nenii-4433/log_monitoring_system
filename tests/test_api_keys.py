import hashlib

from fastapi.testclient import TestClient

import app.main as main
from app.auth import AuthenticatedUser, get_current_user
from app.config import Settings


def test_create_api_key_stores_hash_and_returns_secret_once(
    monkeypatch,
) -> None:
    captured_payload: dict[str, str] = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> list[dict[str, str]]:
            return [
                {
                    "id": "key-123",
                    "name": "Production",
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

        async def post(
            self,
            url: str,
            headers: dict[str, str],
            json: dict[str, str],
        ) -> FakeResponse:
            assert url.endswith("/rest/v1/rpc/create_api_key_for_owner")
            assert headers["apikey"] == "test-secret"
            assert headers["Authorization"] == "Bearer test-secret"
            captured_payload.update(json)
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
                "/v1/organizations/"
                "70000000-0000-4000-8000-000000000001/api-keys",
                json={"name": "  Production  "},
            )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "key-123"
    assert body["name"] == "Production"
    assert body["key"].startswith("lm_")
    assert body["created_at"] == "2026-10-08T00:00:00Z"

    assert captured_payload["p_user_id"] == "verified-user-123"
    assert captured_payload["p_organization_id"] == (
        "70000000-0000-4000-8000-000000000001"
    )
    assert captured_payload["p_name"] == "Production"
    assert captured_payload["p_key_prefix"] == body["key"][:15]
    assert captured_payload["p_secret_hash"] == hashlib.sha256(
        body["key"].encode("utf-8")
    ).hexdigest()
    assert body["key"] != captured_payload["p_secret_hash"]


def test_create_api_key_hides_unauthorized_organization(
    monkeypatch,
) -> None:
    class FakeResponse:
        status_code = 403

    class FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            headers: dict[str, str],
            json: dict[str, str],
        ) -> FakeResponse:
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
        id="verified-member-123"
    )

    try:
        with TestClient(main.app) as client:
            response = client.post(
                "/v1/organizations/"
                "70000000-0000-4000-8000-000000000001/api-keys",
                json={"name": "Production"},
            )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Organization not found"


def test_create_api_key_rejects_extra_request_fields() -> None:
    main.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id="verified-user-123"
    )

    try:
        with TestClient(main.app) as client:
            response = client.post(
                "/v1/organizations/"
                "70000000-0000-4000-8000-000000000001/api-keys",
                json={
                    "name": "Production",
                    "organization_id": "attacker-selected-org",
                },
            )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 422
def test_list_api_keys_returns_metadata_only(monkeypatch) -> None:
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> list[dict[str, str | None]]:
            return [
                {
                    "id": "key-123",
                    "name": "Production",
                    "key_prefix": "lm_abc123",
                    "created_at": "2026-10-08T00:00:00Z",
                    "last_used_at": None,
                    "revoked_at": None,
                    "secret_hash": "must-not-be-returned",
                }
            ]

    class FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            assert timeout == 5.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            headers: dict[str, str],
            json: dict[str, str],
        ) -> FakeResponse:
            assert url.endswith("/rest/v1/rpc/list_api_keys_for_owner")
            assert json == {
                "p_user_id": "verified-user-123",
                "p_organization_id": (
                    "70000000-0000-4000-8000-000000000001"
                ),
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
            response = client.get(
                "/v1/organizations/"
                "70000000-0000-4000-8000-000000000001/api-keys"
            )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": "key-123",
                "name": "Production",
                "key_prefix": "lm_abc123",
                "created_at": "2026-10-08T00:00:00Z",
                "last_used_at": None,
                "revoked_at": None,
            }
        ]
    }
    assert "secret_hash" not in response.text
    assert "must-not-be-returned" not in response.text


def test_revoke_api_key_returns_no_content(monkeypatch) -> None:
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> bool:
            return True

    class FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            assert timeout == 5.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            headers: dict[str, str],
            json: dict[str, str],
        ) -> FakeResponse:
            assert url.endswith("/rest/v1/rpc/revoke_api_key_for_owner")
            assert json == {
                "p_user_id": "verified-owner-123",
                "p_organization_id": (
                    "70000000-0000-4000-8000-000000000001"
                ),
                "p_key_id": "30000000-0000-4000-8000-000000000001",
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
        id="verified-owner-123"
    )

    try:
        with TestClient(main.app) as client:
            response = client.delete(
                "/v1/organizations/"
                "70000000-0000-4000-8000-000000000001/api-keys/"
                "30000000-0000-4000-8000-000000000001"
            )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 204
    assert response.content == b""


def test_revoke_api_key_returns_404_when_key_not_found(
    monkeypatch,
) -> None:
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> bool:
            return False

    class FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            headers: dict[str, str],
            json: dict[str, str],
        ) -> FakeResponse:
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
        id="verified-owner-123"
    )

    try:
        with TestClient(main.app) as client:
            response = client.delete(
                "/v1/organizations/"
                "70000000-0000-4000-8000-000000000001/api-keys/"
                "30000000-0000-4000-8000-000000000099"
            )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "API key not found"