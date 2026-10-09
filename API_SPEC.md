# Multi-Tenant Log Monitoring Platform API

## Status

This document describes the current MVP API and records deferred behavior. The
implemented endpoints are in `app/main.py`; items explicitly marked deferred or
reserved are not available yet.

## Conventions

- Base path: `/v1`
- Request and response bodies use JSON unless stated otherwise.
- Dashboard endpoints require `Authorization: Bearer <Supabase access token>`.
- Supabase Auth owns signup, login, logout, password recovery, and token refresh.
  These are Supabase Auth operations, not custom FastAPI endpoints.
- Ingestion endpoints require an organization API key in
  `Authorization: Bearer <organization-api-key>`.
- Never accept a client-selected `organization_id` for log ingestion.
- Never return stored API-key hashes or log key material in errors or logs.
- Error responses use a stable shape:

  ```json
  {
    "error": {
      "code": "validation_error",
      "message": "The request is invalid."
    }
  }
  ```

- Do not include secrets, raw SQL errors, or cross-tenant resource details in
  error responses.

## Authentication and organization onboarding

### Signup and sign-in

The client uses Supabase Auth to register and sign in. After authentication, it
receives an access token and uses that token for dashboard API requests.

### `POST /v1/organizations`

Creates the first organization during onboarding and atomically makes the signed-in
user its `owner`.

Authentication: Supabase access token.

Request:

```json
{
  "name": "Example Company"
}
```

Success: `201 Created`

```json
{
  "id": "organization-uuid",
  "name": "Example Company",
  "role": "owner",
  "created_at": "2026-10-08T00:00:00Z"
}
```

The operation must fail as a whole if either organization creation or initial owner
membership creation fails. It must not accept a `user_id` or `role` from the
request body. A user may create and own multiple organizations.

### `GET /v1/organizations`

Returns organizations for which the authenticated user has membership.

Success: `200 OK`

```json
{
  "items": [
    {
      "id": "organization-uuid",
      "name": "Example Company",
      "role": "owner"
    }
  ]
}
```

The response must not include organizations the user does not belong to.

## API key management

All key-management operations require a Supabase access token and `owner` role in
the route's organization. Keys are shown in plaintext only in the successful
creation response; the client must be prompted to copy/save the secret at that
time.

Pilot API keys do not expire automatically. Owners can create a replacement key,
then revoke the old key; revoked keys stop working immediately.

### `POST /v1/organizations/{organization_id}/api-keys`

Request:

```json
{
  "name": "Production collector"
}
```

Success: `201 Created`

```json
{
  "id": "api-key-uuid",
  "name": "Production collector",
  "key": "one-time-secret",
  "created_at": "2026-10-08T00:00:00Z"
}
```

Store a cryptographically random key secret as a one-way hash. Never return the
secret again after creation. The API key write path must verify organization
ownership in a narrow server/database operation; do not expose `secret_hash` to
the dashboard.

### `GET /v1/organizations/{organization_id}/api-keys`

Returns key metadata only (`id`, `name`, `key_prefix`, `created_at`,
`last_used_at`, and revocation state). Only owners may list keys.

### `DELETE /v1/organizations/{organization_id}/api-keys/{key_id}`

Revokes a key belonging to that organization. Revocation is idempotent. Only
owners may revoke keys. A key from another organization must not be distinguishable
from a nonexistent key to an unauthorized caller.

## Log event contract

Each individual event is a JSON object with these fields:

```json
{
  "timestamp": "2026-10-08T09:30:00Z",
  "severity": "error",
  "service": "checkout",
  "message": "Payment provider timed out",
  "environment": "production",
  "attributes": {
    "region": "west"
  }
}
```

- Required: `timestamp` (ISO 8601), `service`, and `message`.
- Optional: `severity` (sender-provided hint), `environment`, and `attributes`
  (JSON object).
- Allowed sender severity values: `trace`, `debug`, `info`, `warning`, `error`,
  `critical`.
- Maximum serialized event size: 256 KB.
- The v1 API accepts one event per request. Batch ingestion is deferred until
  limits and partial-failure behavior are specified.
- Reject unknown fields, including `organization_id`, so a client cannot attempt
  to select a tenant or silently rely on ignored fields.

### `POST /v1/logs`

Authentication: organization API key in the Bearer authorization header.

The server validates the event, checks key status, derives the organization only
from the key record, and atomically stores the log and its processing queue
message. The sender's optional severity is stored separately as
`source_severity`. The response/search field `severity` is reserved for the
system prediction and remains `null` until the background prediction worker
processes the queued log.

Pilot quota and rate-limit enforcement is not implemented in the first ingestion
increment. Do not treat this endpoint as production-ready until agreed limits and
enforcement are implemented and tested.

Success: `202 Accepted`

```json
{
  "id": "log-uuid",
  "accepted_at": "2026-10-08T09:30:01Z"
}
```

Failures:

- `400 Bad Request`: malformed JSON or invalid event fields.
- `401 Unauthorized`: absent, unknown, or revoked API key, with a generic message.
- `413 Content Too Large`: event exceeds 256 KB.
- `429 Too Many Requests`: reserved for the later quota/rate-limit implementation.
- `503 Service Unavailable`: event could not be durably stored and queued.

Do not return `202` unless both durable log storage and queue insertion succeed.

## Log search

### `GET /v1/logs`

Authentication: Supabase access token.

Required query parameter:

- `organization_id`: organization to search; the authenticated user must be a
  member. This selects a dashboard scope and is never trusted as proof of access.

Optional query parameters:

- `from`, `to`: ISO 8601 event-time bounds.
- `severity`: one allowed severity value; may be repeatable for multiple values.
- `service`: exact service filter.
- `environment`: exact environment filter.
- `limit`: default 50, maximum 100.
- `cursor`: opaque pagination cursor.

Success: `200 OK`

```json
{
  "items": [
    {
      "id": "log-uuid",
      "timestamp": "2026-10-08T09:30:00Z",
      "received_at": "2026-10-08T09:30:01Z",
      "severity": null,
      "source_severity": "warning",
      "prediction_status": "pending",
      "prediction_confidence": null,
      "prediction_reason": null,
      "prediction_method": null,
      "prediction_error": null,
      "service": "checkout",
      "environment": "production",
      "message": "Payment provider timed out",
      "attributes": {
        "region": "west"
      }
    }
  ],
  "next_cursor": null
}
```

The API calls `search_logs_for_member` with its server-side database credential.
That function must verify the authenticated user's membership before returning
logs; filtering by `organization_id` alone is not an authorization control, and
the privileged server credential means RLS alone does not protect this request.
The `severity` response field and severity filter refer to the system prediction;
`source_severity` is the optional value sent by the log producer.
Each search result also includes `prediction_status` (`pending`, `complete`, or
`failed`), nullable `prediction_confidence`, `prediction_reason`, and
`prediction_error`.

### Organization service criticality

`GET /v1/organizations/{organization_id}/service-criticalities` returns the
services configured for the organization and their `low`, `normal`, `high`, or
`critical` importance. Any organization member may view settings. Owners can
create or update one using `PUT` with `{"service":"payments","criticality":"high"}`.
The worker treats services without a setting as `normal`.

The severity worker reads queued events, computes organization-scoped context,
and updates prediction metadata asynchronously. Run it separately from the API
with `python -m app.severity_worker`. It uses the local Ollama URL/model settings
(`OLLAMA_URL` and `OLLAMA_MODEL`); uncertain predictions are retried up to three
times before being marked `failed`. It does not send log content to a hosted LLM.
Return the same not-found response for inaccessible organization IDs; do not
disclose whether another organization's ID exists.

## Health

### `GET /health`

No authentication required. Returns process health only and must not disclose
database credentials, customer data, or detailed dependency errors.

Success: `200 OK`

```json
{
  "status": "ok"
}
```

## Deferred endpoints and behavior

- Invitations and adding organization members.
- Batch ingestion and partial success.
- Error-group endpoints and natural-language search.
- Alert rules and delivery status.
- Billing and payments.
- Exact quota plan definitions and quota-reset behavior.

## Decisions to confirm before implementation

1. Are organization `name` normalization and uniqueness required?
2. What should happen when a user requests an inaccessible organization: `403` or
   non-disclosing `404` for every organization-scoped endpoint?
3. What API-key format, expiration policy, and rotation overlap should be used?
4. Which quotas apply to the pilot, and how are limit windows reset?
5. Should `message` and `attributes` be returned verbatim in search, or should
   sensitive-field redaction be part of ingestion?
6. What pagination sort order and cursor lifetime are required?
