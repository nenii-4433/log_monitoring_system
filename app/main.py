import base64
import hashlib
import json
import secrets
from datetime import datetime
from uuid import UUID

import httpx
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.auth import AuthenticatedUser, get_current_user
from app.config import get_settings
from app.schemas import LogEvent

app = FastAPI(title="Log Monitoring API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
_api_key_bearer = HTTPBearer(auto_error=False)
_MAX_LOG_EVENT_BYTES = 262_144


def _encode_log_cursor(timestamp: str, log_id: str) -> str:
    cursor_data = json.dumps(
        {"timestamp": timestamp, "id": log_id},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(cursor_data).decode("ascii").rstrip("=")


def _decode_log_cursor(cursor: str) -> tuple[str, str]:
    try:
        padded_cursor = cursor + "=" * (-len(cursor) % 4)
        cursor_bytes = base64.b64decode(
            padded_cursor,
            altchars=b"-_",
            validate=True,
        )
        decoded = json.loads(cursor_bytes)
        if (
            not isinstance(decoded, dict)
            or not isinstance(decoded.get("timestamp"), str)
            or not isinstance(decoded.get("id"), str)
        ):
            raise ValueError("cursor fields are invalid")
        timestamp = decoded["timestamp"]
        log_id = decoded["id"]
        parsed_timestamp = datetime.fromisoformat(
            timestamp.replace("Z", "+00:00")
        )
        parsed_id = UUID(log_id)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pagination cursor",
        ) from exc

    if parsed_timestamp.tzinfo is None or parsed_timestamp.utcoffset() is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pagination cursor",
        )

    return parsed_timestamp.isoformat(), str(parsed_id)


class CreateOrganizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Organization name must not be blank")
        return value


class ServiceCriticalityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str = Field(min_length=1, max_length=120)
    criticality: str

    @field_validator("service")
    @classmethod
    def service_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Service must not be blank")
        return value.strip()

    @field_validator("criticality")
    @classmethod
    def criticality_must_be_allowed(cls, value: str) -> str:
        if value not in {"low", "normal", "high", "critical"}:
            raise ValueError("Invalid service criticality")
        return value


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/me")
async def get_me(
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, str]:
    return {"id": user.id}


@app.post("/v1/organizations", status_code=status.HTTP_201_CREATED)
async def create_organization(
    request: CreateOrganizationRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, str]:
    settings = get_settings()
    url = f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/create_organization_for_user"
    headers = {
        "apikey": settings.supabase_secret_key,
        "Authorization": f"Bearer {settings.supabase_secret_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                url,
                headers=headers,
                json={"p_user_id": user.id, "p_name": request.name},
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Organization service unavailable",
        ) from exc

    if response.status_code != status.HTTP_200_OK:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Organization service unavailable",
        )

    try:
        result = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid response from organization service",
        ) from exc

    if not isinstance(result, list) or len(result) != 1:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid response from organization service",
        )

    organization = result[0]
    if (
        not isinstance(organization, dict)
        or not all(
            isinstance(organization.get(field), str)
            for field in ("id", "name", "role", "created_at")
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid response from organization service",
        )

    return {
        "id": organization["id"],
        "name": organization["name"],
        "role": organization["role"],
        "created_at": organization["created_at"],
    }


@app.get("/v1/organizations")
async def list_organizations(
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, list[dict[str, str]]]:
    settings = get_settings()
    url = f"{settings.supabase_url.rstrip('/')}/rest/v1/organization_members"
    headers = {
        "apikey": settings.supabase_secret_key,
        "Authorization": f"Bearer {settings.supabase_secret_key}",
    }
    params = {
        "select": "role,organization:organizations(id,name)",
        "user_id": f"eq.{user.id}",
        "order": "organization_id.asc",
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url, headers=headers, params=params)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Organization service unavailable",
        ) from exc

    if response.status_code != status.HTTP_200_OK:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Organization service unavailable",
        )

    try:
        rows = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid response from organization service",
        ) from exc

    if not isinstance(rows, list):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid response from organization service",
        )

    items = []
    for row in rows:
        if not isinstance(row, dict):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Invalid response from organization service",
            )

        organization = row.get("organization")
        role = row.get("role")
        if (
            not isinstance(organization, dict)
            or not isinstance(organization.get("id"), str)
            or not isinstance(organization.get("name"), str)
            or not isinstance(role, str)
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Invalid response from organization service",
            )

        items.append(
            {
                "id": organization["id"],
                "name": organization["name"],
                "role": role,
            }
        )

    return {"items": items}


@app.get("/v1/organizations/{organization_id}/service-criticalities")
async def list_service_criticalities(
    organization_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, list[dict[str, str]]]:
    settings = get_settings()
    url = (
        f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/"
        "get_service_criticalities"
    )
    headers = {
        "apikey": settings.supabase_secret_key,
        "Authorization": f"Bearer {settings.supabase_secret_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                url,
                headers=headers,
                json={
                    "p_user_id": user.id,
                    "p_organization_id": str(organization_id),
                },
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service settings unavailable",
        ) from exc

    if response.status_code == status.HTTP_403_FORBIDDEN:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    if response.status_code != status.HTTP_200_OK:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service settings unavailable",
        )

    try:
        rows = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid response from service settings",
        ) from exc
    if not isinstance(rows, list) or any(
        not isinstance(row, dict)
        or not isinstance(row.get("service"), str)
        or not isinstance(row.get("criticality"), str)
        or row["criticality"] not in {"low", "normal", "high", "critical"}
        for row in rows
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid response from service settings",
        )
    return {"items": rows}


@app.put(
    "/v1/organizations/{organization_id}/service-criticalities",
)
async def set_service_criticality(
    organization_id: UUID,
    request: ServiceCriticalityRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, str]:
    settings = get_settings()
    url = (
        f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/"
        "set_service_criticality"
    )
    headers = {
        "apikey": settings.supabase_secret_key,
        "Authorization": f"Bearer {settings.supabase_secret_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                url,
                headers=headers,
                json={
                    "p_user_id": user.id,
                    "p_organization_id": str(organization_id),
                    "p_service": request.service,
                    "p_criticality": request.criticality,
                },
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service settings unavailable",
        ) from exc

    if response.status_code == status.HTTP_403_FORBIDDEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organization owners can change service criticality",
        )
    if response.status_code != status.HTTP_200_OK:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service settings unavailable",
        )

    try:
        rows = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid response from service settings",
        ) from exc
    if (
        not isinstance(rows, list)
        or len(rows) != 1
        or not isinstance(rows[0], dict)
        or rows[0].get("service") != request.service
        or rows[0].get("criticality") != request.criticality
        or not isinstance(rows[0].get("updated_at"), str)
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid response from service settings",
        )
    return {
        "service": rows[0]["service"],
        "criticality": rows[0]["criticality"],
        "updated_at": rows[0]["updated_at"],
    }


@app.delete(
    "/v1/organizations/{organization_id}/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_api_key(
    organization_id: UUID,
    key_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
) -> Response:
    settings = get_settings()
    url = (
        f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/"
        "revoke_api_key_for_owner"
    )
    headers = {
        "apikey": settings.supabase_secret_key,
        "Authorization": f"Bearer {settings.supabase_secret_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "p_user_id": user.id,
        "p_organization_id": str(organization_id),
        "p_key_id": str(key_id),
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key service unavailable",
        ) from exc

    if response.status_code == status.HTTP_403_FORBIDDEN:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )

    if response.status_code != status.HTTP_200_OK:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key service unavailable",
        )

    try:
        revoked = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid response from API key service",
        ) from exc

    if not isinstance(revoked, bool):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid response from API key service",
        )

    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post(
    "/v1/logs",
    status_code=status.HTTP_202_ACCEPTED,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": LogEvent.model_json_schema(),
                }
            },
        }
    },
)
async def ingest_log(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_api_key_bearer),
) -> dict[str, str]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    api_key = credentials.credentials
    if not api_key.startswith("lm_") or len(api_key) < 20:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    content_type = request.headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A JSON log event is required",
        )

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Content-Length header",
            ) from exc
        if declared_length < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Content-Length header",
            )
        if declared_length > _MAX_LOG_EVENT_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Log event exceeds 256 KB",
            )

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _MAX_LOG_EVENT_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Log event exceeds 256 KB",
            )

    try:
        event = LogEvent.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid log event",
        ) from exc

    settings = get_settings()
    url = (
        f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/"
        "ingest_log_for_api_key"
    )
    headers = {
        "apikey": settings.supabase_secret_key,
        "Authorization": f"Bearer {settings.supabase_secret_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "p_key_prefix": api_key[:15],
        "p_secret_hash": hashlib.sha256(api_key.encode("utf-8")).hexdigest(),
        "p_event_timestamp": event.timestamp.isoformat(),
        "p_severity": event.severity,
        "p_service": event.service,
        "p_environment": event.environment,
        "p_message": event.message,
        "p_attributes": event.attributes,
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Log ingestion service unavailable",
        ) from exc

    if response.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if response.status_code == status.HTTP_400_BAD_REQUEST:
        try:
            error_body = response.json()
        except ValueError:
            error_body = None
        if isinstance(error_body, dict) and error_body.get("code") == "28000":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
                headers={"WWW-Authenticate": "Bearer"},
            )

    if response.status_code != status.HTTP_200_OK:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Log ingestion service unavailable",
        )

    try:
        result = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid response from log ingestion service",
        ) from exc

    if (
        not isinstance(result, list)
        or len(result) != 1
        or not isinstance(result[0], dict)
        or not isinstance(result[0].get("id"), str)
        or not isinstance(result[0].get("accepted_at"), str)
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid response from log ingestion service",
        )

    return {
        "id": result[0]["id"],
        "accepted_at": result[0]["accepted_at"],
    }


@app.get("/v1/logs")
async def search_logs(
    organization_id: UUID,
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    severity: list[str] | None = Query(default=None),
    service: str | None = Query(default=None, max_length=120),
    environment: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, min_length=1, max_length=512),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, object]:
    if (
        from_time is not None
        and (from_time.tzinfo is None or from_time.utcoffset() is None)
    ) or (
        to_time is not None
        and (to_time.tzinfo is None or to_time.utcoffset() is None)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Time filters must include a timezone",
        )

    if from_time is not None and to_time is not None and from_time > to_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="from must be earlier than or equal to to",
        )

    allowed_severities = {
        "trace",
        "debug",
        "info",
        "warning",
        "error",
        "critical",
    }
    if severity is not None and any(
        value not in allowed_severities for value in severity
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid severity filter",
        )

    before_timestamp = None
    before_id = None
    if cursor is not None:
        before_timestamp, before_id = _decode_log_cursor(cursor)

    settings = get_settings()
    url = (
        f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/"
        "search_logs_for_member"
    )
    headers = {
        "apikey": settings.supabase_secret_key,
        "Authorization": f"Bearer {settings.supabase_secret_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "p_user_id": user.id,
        "p_organization_id": str(organization_id),
        "p_from": from_time.isoformat() if from_time is not None else None,
        "p_to": to_time.isoformat() if to_time is not None else None,
        "p_severities": severity,
        "p_service": service,
        "p_environment": environment,
        "p_before_timestamp": before_timestamp,
        "p_before_id": before_id,
        "p_limit": limit + 1,
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Log search service unavailable",
        ) from exc

    if response.status_code == status.HTTP_403_FORBIDDEN:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    if response.status_code != status.HTTP_200_OK:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Log search service unavailable",
        )

    try:
        rows = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid response from log search service",
        ) from exc

    if not isinstance(rows, list):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid response from log search service",
        )

    expected_string_fields = (
        "id",
        "event_timestamp",
        "received_at",
        "service",
        "message",
    )
    items: list[dict[str, object]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict) or not all(
            isinstance(row.get(field), str) for field in expected_string_fields
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Invalid response from log search service",
            )

        row_severity = row.get("severity")
        row_source_severity = row.get("source_severity")
        prediction_status = row.get("prediction_status")
        prediction_reason = row.get("prediction_reason")
        prediction_method = row.get("prediction_method")
        prediction_error = row.get("prediction_error")
        if (
            row_severity is not None
            and not isinstance(row_severity, str)
        ) or (
            row_source_severity is not None
            and not isinstance(row_source_severity, str)
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Invalid response from log search service",
            )
        if prediction_status not in {"pending", "complete", "failed"}:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Invalid response from log search service",
            )
        if (
            prediction_reason is not None
            and not isinstance(prediction_reason, str)
        ) or (
            prediction_method is not None
            and not isinstance(prediction_method, str)
        ) or (
            prediction_error is not None
            and not isinstance(prediction_error, str)
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Invalid response from log search service",
            )
        confidence = row.get("prediction_confidence")
        if (
            confidence is not None
            and (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not 0.0 <= confidence <= 1.0
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Invalid response from log search service",
            )

        try:
            UUID(row["id"])
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Invalid response from log search service",
            ) from exc

        row_environment = row.get("environment")
        row_attributes = row.get("attributes")
        if row_environment is not None and not isinstance(row_environment, str):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Invalid response from log search service",
            )
        if row_attributes is not None and not isinstance(row_attributes, dict):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Invalid response from log search service",
            )

        items.append(
            {
                "id": row["id"],
                "timestamp": row["event_timestamp"],
                "received_at": row["received_at"],
                "severity": row_severity,
                "source_severity": row_source_severity,
                "prediction_status": prediction_status,
                "prediction_confidence": confidence,
                "prediction_reason": prediction_reason,
                "prediction_method": prediction_method,
                "prediction_error": prediction_error,
                "service": row["service"],
                "environment": row_environment,
                "message": row["message"],
                "attributes": row_attributes,
            }
        )

    next_cursor = None
    if len(rows) > limit:
        last_row = rows[limit - 1]
        if not isinstance(last_row, dict):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Invalid response from log search service",
            )
        timestamp = last_row.get("event_timestamp")
        log_id = last_row.get("id")
        if not isinstance(timestamp, str) or not isinstance(log_id, str):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Invalid response from log search service",
            )
        next_cursor = _encode_log_cursor(timestamp, log_id)

    return {"items": items, "next_cursor": next_cursor}


class CreateApiKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("API key name must not be blank")
        return value


@app.post(
    "/v1/organizations/{organization_id}/api-keys",
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    organization_id: UUID,
    request: CreateApiKeyRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, str]:
    settings = get_settings()

    api_key = f"lm_{secrets.token_urlsafe(32)}"
    key_prefix = api_key[:15]
    secret_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    url = (
        f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/"
        "create_api_key_for_owner"
    )
    headers = {
        "apikey": settings.supabase_secret_key,
        "Authorization": f"Bearer {settings.supabase_secret_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "p_user_id": user.id,
        "p_organization_id": str(organization_id),
        "p_name": request.name,
        "p_key_prefix": key_prefix,
        "p_secret_hash": secret_hash,
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key service unavailable",
        ) from exc

    if response.status_code == status.HTTP_403_FORBIDDEN:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    if response.status_code != status.HTTP_200_OK:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key service unavailable",
        )

    try:
        result = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid response from API key service",
        ) from exc

    if not isinstance(result, list) or len(result) != 1:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid response from API key service",
        )

    metadata = result[0]
    if (
        not isinstance(metadata, dict)
        or not all(
            isinstance(metadata.get(field), str)
            for field in ("id", "name", "created_at")
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid response from API key service",
        )

    return {
        "id": metadata["id"],
        "name": metadata["name"],
        "key": api_key,
        "created_at": metadata["created_at"],
    }
@app.get("/v1/organizations/{organization_id}/api-keys")
async def list_api_keys(
    organization_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, list[dict[str, str | None]]]:
    settings = get_settings()
    url = (
        f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/"
        "list_api_keys_for_owner"
    )
    headers = {
        "apikey": settings.supabase_secret_key,
        "Authorization": f"Bearer {settings.supabase_secret_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "p_user_id": user.id,
        "p_organization_id": str(organization_id),
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key service unavailable",
        ) from exc

    if response.status_code == status.HTTP_403_FORBIDDEN:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    if response.status_code != status.HTTP_200_OK:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key service unavailable",
        )

    try:
        rows = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid response from API key service",
        ) from exc

    if not isinstance(rows, list):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid response from API key service",
        )

    items: list[dict[str, str | None]] = []
    for row in rows:
        if not isinstance(row, dict) or not all(
            isinstance(row.get(field), str)
            for field in ("id", "name", "key_prefix", "created_at")
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Invalid response from API key service",
            )

        last_used_at = row.get("last_used_at")
        revoked_at = row.get("revoked_at")
        if (
            last_used_at is not None
            and not isinstance(last_used_at, str)
        ) or (
            revoked_at is not None
            and not isinstance(revoked_at, str)
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Invalid response from API key service",
            )

        items.append(
            {
                "id": row["id"],
                "name": row["name"],
                "key_prefix": row["key_prefix"],
                "created_at": row["created_at"],
                "last_used_at": last_used_at,
                "revoked_at": revoked_at,
            }
        )

    return {"items": items}