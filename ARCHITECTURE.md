# Multi-Tenant Log Monitoring Platform

## Architecture draft

- Status: Draft for review
- Version: 0.1
- Related requirements: [REQUIREMENTS.md](./REQUIREMENTS.md)

## Goals for the first working increment

1. Authenticate users and associate them with organizations.
2. Accept organization-scoped JSON logs using API keys.
3. Store and search logs without exposing another organization's data.
4. Process accepted logs asynchronously using Supabase `pgmq`.
5. Prove tenant isolation with automated tests before adding advanced features.

LLM explanations are deferred until ingestion and search work. The first increment
will not require an LLM provider or API key.

## Technology direction

- Frontend: React.
- API and workers: Python with FastAPI.
- Authentication and database: Supabase Auth and PostgreSQL.
- Queue: Supabase `pgmq`.
- Realtime dashboard updates: Supabase Realtime, after the basic log flow works.
- NLP: Python components introduced after ingestion and search are reliable.

## Main data flow

1. A user's browser authenticates with Supabase Auth and selects an organization
   of which the user is a member.
2. A client application sends a JSON log event to FastAPI with its organization
   API key.
3. FastAPI validates the event shape and size, extracts the key prefix, and
   computes the key hash.
4. A restricted database function verifies the active key hash, derives the
   organization from the key record, updates key-use metadata, stores the log,
   and sends a `log_processing` message in the same transaction.
5. The Python worker processes the queued log and records derived
   severity/grouping data.
6. The dashboard searches only organizations accessible to the signed-in user.

The browser must never receive a Supabase service-role secret or an ingestion API
key. Clients must not be allowed to choose the organization that owns a log by
providing an organization ID in the event.

## Conceptual data model

- `organizations`: organization identity and lifecycle timestamps.
- `organization_members`: organization-to-user membership and role (`owner` or
  `member`); invitations are deferred.
- `api_keys`: organization, display name, lookup prefix, secret hash, creation,
  last-used, and revocation metadata. The plaintext key is shown only at creation.
- `logs`: organization ID, event timestamp, server receive timestamp, severity,
  service, optional environment, message, and optional JSON attributes.
- `error_groups`: organization-scoped grouping fingerprint and summary fields;
  introduce when the NLP grouping milestone begins.
- `alerts`: organization-scoped alert rules and delivery state; introduce when
  the alert milestone begins.

Every organization-owned record must have a non-null organization ID. Add indexes
for organization-scoped time searches and the filters accepted by the API. Use
foreign keys and uniqueness constraints that include the organization ID wherever
they enforce tenant-local relationships.

## First database schema and access-policy proposal

This is a design contract, not migration SQL. Confirm it before making migrations
executable.

### Tables

- `organizations`
  - `id`: UUID primary key.
  - `name`: required organization display name.
  - `created_at`, `updated_at`: server-generated timestamps.
- `organization_members`
  - `organization_id`: required foreign key to `organizations`.
  - `user_id`: required UUID referencing the Supabase Auth user.
  - `role`: required enum/check value, `owner` or `member`.
  - `created_at`: server-generated timestamp.
  - Primary key `(organization_id, user_id)`. Invitation workflows are out of
    scope; the initial organization-creation flow creates its owner membership
    atomically.
- `api_keys`
  - `id`: UUID primary key.
  - `organization_id`: required organization foreign key.
  - `name`: owner-provided display name.
  - `key_prefix`: non-secret lookup prefix, unique.
  - `secret_hash`: required hash of a cryptographically random key secret; never
    store or return the plaintext secret after the one-time creation response.
  - `created_at`, `last_used_at`, `revoked_at`: server-managed timestamps.
- `logs`
  - `id`: UUID primary key.
  - `organization_id`: required organization foreign key.
  - `event_timestamp`: client-provided validated timestamp.
  - `received_at`: server-generated timestamp.
  - `severity`: constrained to `trace`, `debug`, `info`, `warning`, `error`, or
    `critical`.
  - `service`: required bounded-length text.
  - `environment`: optional bounded-length text.
  - `message`: required bounded-length text.
  - `attributes`: optional JSON object, not an arbitrary JSON scalar or array.
  - Add indexes beginning with `organization_id` for time-ordered search and
    expected severity/service/environment filters. Enforce the 256 KB event size
    at the API boundary and validate field limits before insertion.

Use composite foreign keys for tenant-local relationships, such as
`(organization_id, user_id)` membership references where relevant. Add a unique
constraint or index to prevent duplicate active key prefixes. Retention deletes
logs using server-side `received_at`, in bounded batches.

### Dashboard access policy

- Enable RLS on all four tables and grant authenticated users only the table
  operations needed by the dashboard.
- An authenticated user may read an organization only when a matching membership
  row exists for `auth.uid()`.
- Members and owners may read logs only for organizations where they have a
  membership.
- Only owners may create, list, or revoke API keys. For any direct dashboard
  metadata read, grant `SELECT` only on metadata columns and do not grant access
  to `secret_hash`; RLS must still restrict rows to the owner's organization.
  Key creation must show the plaintext secret once and never return it again.
- Do not expose direct browser writes to logs, API-key hashes, or membership rows.
- Organization creation and initial owner membership are created atomically
  through a narrowly scoped server/database operation. Do not allow the browser
  to self-assign an owner role by directly inserting a membership row.

### API-key ingestion operation

- Generate API keys from cryptographically secure random bytes. Store a lookup
  prefix and a one-way hash; compare hashes in constant time where the chosen
  implementation permits it. Apply rate limits to both valid and invalid keys.
- FastAPI validates request shape and size, then invokes one narrowly scoped
  database function with the presented key and event fields. The function
  resolves an active key by prefix and hash, obtains `organization_id` from that
  key row, inserts the log, and enqueues processing in the same database
  transaction. It accepts no organization ID from the caller.
- Return only the accepted log ID or a generic authentication failure; do not
  reveal whether a key prefix exists or which organization owns it.
- Do not grant the function general-purpose table access or expose it to browser
  roles. Restrict execution to the backend path. If the selected Supabase access
  method cannot provide that restriction, revise the design before migration.

### Required isolation tests

1. A member of Organization A cannot select logs, keys, or organization metadata
   belonging to Organization B by changing IDs or filters.
2. A member cannot create/revoke API keys or alter membership roles.
3. An Organization A API key always creates an Organization A log, even if the
   request includes an unexpected tenant field; preferably reject unknown fields.
4. Invalid, revoked, and unknown API keys produce indistinguishable auth failures
   and create neither logs nor queue messages.
5. The ingestion function cannot be executed by `anon` or `authenticated`, and
   cannot read or write arbitrary tenant data.
6. Log and queue insertion either both succeed or both roll back.
7. Organization creation cannot leave an organization without its initial owner.

## Tenant isolation requirements

- Supabase Auth identifies dashboard users; database policies must verify
  organization membership for every organization-owned read and write.
- FastAPI derives an ingestion request's organization from its validated API key;
  never trust a client-supplied tenant ID.
- Every tenant-owned table must have RLS enabled and tested.
- For API-key ingestion, FastAPI calls a narrow database RPC with the presented
  key prefix, hash, and validated event. The `ingest_log_for_api_key` function
  looks up the active key hash, derives the organization ID from the matching key
  record, and inserts the log and queue message. The caller never supplies the
  organization ID.
- This RPC is a deliberate privileged path; do not claim that RLS alone protects
  it. Before implementing it, verify the Supabase role and function ownership
  model, use a minimally privileged function owner where supported, and grant
  function execution only to the backend role that needs it.
- If implemented as `SECURITY DEFINER`, set an empty `search_path`, schema-qualify
  every relation and function call, validate every input, return only the minimum
  result, and revoke default execution from `PUBLIC`, `anon`, and other unused
  roles. The function must not permit arbitrary tenant selection or general table
  reads/writes.
- A Supabase secret/service-role credential bypasses RLS. Keep it only in the
  backend, never in the browser or source control, and do not treat possession of
  that credential as tenant isolation.
- Test that Organization A cannot read, change, or trigger actions on Organization
  B's data, including through filters, background jobs, and realtime subscriptions.

See [API_SPEC.md](./API_SPEC.md) for the draft API contract, including Supabase
Auth onboarding, atomic initial organization ownership, API-key management,
ingestion, log search, error behavior, and deferred endpoints.

## Reliability and data handling

- Queue work only after the log is durably accepted. Test the failure boundary
  between storage and queueing so accepted logs are not silently left unprocessed.
- Workers must retry transient failures and make processing safe to repeat.
- Delete raw logs after 30 days; define how derived records are deleted or retained
  with their source logs before implementing retention jobs.
- Do not log API key material or raw log messages in operational logs by default.
- Keep secrets in local environment configuration or a secret manager, never in
  source control.

## Implementation sequence after design approval

1. Scaffold the backend, frontend, local development setup, and basic checks.
2. Define migrations for organizations, memberships, API keys, and logs; implement
   and test the chosen RLS path.
3. Implement authentication, organization membership, and API-key management.
4. Implement JSON log ingestion, durable queueing, and database search.
5. Add the worker and initial NLP severity/grouping increment.
6. Build the dashboard and realtime updates.
7. Add LLM explanations after selecting a provider; then add alerts and operational
   quotas in separate tested increments.

## Decisions still needed

- Validate the restricted RPC owner's privileges and function-execution grants
  against the actual Supabase project before writing migrations.
- Define exact membership roles and organization invitation behavior.
- Define ingestion batching, pagination, quota behavior, and API error responses.
- Confirm the provisional peak of 10 logs/second per organization and expected
  concurrent dashboard users before load-test design.
- Define retention/deletion behavior for derived records, error groups, and alert
  delivery data.
- Choose the NLP evaluation dataset and agree how to measure dashboard load time.

## Security references

- [Supabase Row Level Security](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [Supabase API keys](https://supabase.com/docs/guides/api/api-keys)
- [Supabase database functions](https://supabase.com/docs/guides/database/functions)
