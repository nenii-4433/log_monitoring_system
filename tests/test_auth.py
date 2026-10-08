import asyncio

import httpx
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.auth import get_current_user


def test_missing_credentials_are_rejected() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(get_current_user(None))

    assert error.value.status_code == 401


def test_valid_token_returns_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> dict[str, str]:
            return {"id": "user-123"}

    class FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            assert timeout == 5.0

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(
            self, url: str, headers: dict[str, str]
        ) -> FakeResponse:
            assert url.endswith("/auth/v1/user")
            assert headers["Authorization"] == "Bearer test-token"
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials="test-token",
    )
    user = asyncio.run(get_current_user(credentials))

    assert user.id == "user-123"


def test_invalid_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status_code = 401

    class FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(
            self, url: str, headers: dict[str, str]
        ) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials="invalid-test-token",
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(get_current_user(credentials))

    assert error.value.status_code == 401