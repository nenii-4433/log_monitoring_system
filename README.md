# Multi-Tenant Log Monitoring System

A local MVP for collecting structured application logs in organization-scoped
workspaces. The project includes a FastAPI ingestion/search API, Supabase Auth and
PostgreSQL schema, and a React dashboard for managing organizations, API keys, and
searching logs.

> **Project status:** Local development MVP. The core sign-in, organization, API
> key, ingestion, and search flow has been exercised locally. This project is not
> production-ready and has not been deployed as a hosted service.

## Features

- Supabase Auth sign-up and sign-in.
- Organization creation and membership-aware organization listing.
- Owner-only API key creation, listing, and revocation. Plaintext keys are shown
  only once; stored keys are hashed.
- Structured JSON log ingestion, with organization identity derived from the
  API key rather than supplied by the client.
- Organization membership-checked log search with time, severity, service, and
  environment filters and cursor pagination.
- A React dashboard with organization selection, API key management, log search,
  and five-second polling for the newest results while the page is visible.
- A demo log generator and JSON-lines file follower for local ingestion testing.
- PostgreSQL migrations and database tests for tenant isolation and core database
  operations.

## Architecture

```text
Application / demo log file
          |
          | JSON event + organization API key
          v
     FastAPI API
          |
          +------> Supabase PostgreSQL (store log)
          |                 |
          |                 +----> pgmq processing queue
          |
          +<------ member-checked log search
                    ^
                    |
              React dashboard
                    |
                    +------ Supabase Auth (user session)
```

The ingestion API validates each event, resolves its organization from the active
API key, stores it, and enqueues a processing message. The dashboard searches
through a backend function that checks organization membership. The browser uses
only Supabase's publishable key; the Supabase secret remains in the backend
environment.

The queue is created and receives messages, but a background consumer/worker is
not yet implemented. Dashboard updates use five-second polling, not Supabase
Realtime push.

## Requirements

- Python 3.11 or newer (the local MVP has been exercised with Python 3.14).
- Node.js 20.19+ or 22.12+ and npm (Vite 7 requirement).
- Docker Desktop running.
- Supabase CLI. The commands below use `npx supabase`.

## Local setup (Windows PowerShell)

Run commands from the project root.

### 1. Start Supabase

```powershell
npx supabase start
npx supabase migration up --local
```

The local Supabase services use `http://127.0.0.1:54321`; Studio is normally at
`http://127.0.0.1:54323`. `npx supabase status` displays local credentials. Treat
the Secret key as sensitive and never commit or share it.

### 2. Configure and run the backend

```powershell
Copy-Item .env.example .env
```

Edit `.env` and set:

- `SUPABASE_URL` to the local Supabase API URL.
- `SUPABASE_PUBLISHABLE_KEY` to the local Supabase publishable/anon key.
- `SUPABASE_SECRET_KEY` to the local Supabase Secret/service-role key.

Create a virtual environment and install dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Start FastAPI and leave this terminal open:

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Check the health endpoint at `http://127.0.0.1:8000/health`.

### 3. Configure and run the dashboard

In a second terminal:

```powershell
Copy-Item frontend\.env.example frontend\.env
```

Edit `frontend\.env` and set `VITE_SUPABASE_PUBLISHABLE_KEY` to the local
Supabase publishable/anon key. Keep the Supabase Secret key out of this file.
The local URL and API URL defaults in the example are suitable for the commands
above.

Install packages and start Vite:

```powershell
Set-Location frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. Sign up or sign in, create/select an organization,
and create an organization API key. Copy the plaintext key when it is shown; it
cannot be retrieved later. Use a different key per environment or log source and
revoke test keys when they are no longer needed.

## Run tests and build

From the project root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npx supabase test db
```

Build and type-check the dashboard:

```powershell
Set-Location frontend
npm ci
npm run build
```

The database tests require the local Supabase Docker stack to be running.

## Test log-file ingestion locally

The demo simulates an application writing one JSON event per line and a separate
collector following the file and forwarding new lines to the API. It does not
capture the project's own Uvicorn logs.

1. In the dashboard, select the organization to test and create an API key.
2. Copy that key. Open a PowerShell terminal at the project root and start the
   follower (it skips existing lines and watches for new lines):

   ```powershell
   if (-not (Test-Path .\demo\server.log)) {
       New-Item -ItemType File -Path .\demo\server.log | Out-Null
   }
   $env:LOG_MONITORING_API_KEY = (Get-Clipboard -Raw).Trim()
   .\.venv\Scripts\python.exe demo\follow_server_log.py demo\server.log
   ```

   Keep this terminal open. The API key is read from this process's environment;
   do not paste the key into source code or commit it.

3. In another PowerShell terminal at the project root, append five test events
   without sending them directly to the API:

   ```powershell
   .\.venv\Scripts\python.exe demo\server_log_demo.py --file-only --count 5 --interval 2
   ```

4. The follower reports each forwarded line. Keep the dashboard on the newest
   results; newly ingested logs should appear through its five-second refresh.
5. Press **Ctrl+C** in the follower terminal to stop it. The generated
   `demo\server.log` is ignored by Git.

To generate events and send them directly without the file follower:

```powershell
.\.venv\Scripts\python.exe demo\server_log_demo.py --count 5 --interval 3
```

That command prompts for the API key using hidden input. Alternatively, copy the
key to the clipboard and set it only for the current PowerShell process:

```powershell
$env:LOG_MONITORING_API_KEY = (Get-Clipboard -Raw).Trim()
try {
    .\.venv\Scripts\python.exe demo\server_log_demo.py --count 5 --interval 3
}
finally {
    Remove-Item Env:\LOG_MONITORING_API_KEY -ErrorAction SilentlyContinue
}
```

## API overview

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Process health check |
| `GET` | `/v1/me` | Validate the signed-in user |
| `POST` | `/v1/organizations` | Create an organization and its owner membership |
| `GET` | `/v1/organizations` | List organizations for the signed-in user |
| `POST` | `/v1/organizations/{organization_id}/api-keys` | Create an owner-scoped ingestion key |
| `GET` | `/v1/organizations/{organization_id}/api-keys` | List owner-visible key metadata |
| `DELETE` | `/v1/organizations/{organization_id}/api-keys/{key_id}` | Revoke an organization key |
| `POST` | `/v1/logs` | Ingest one structured log event using an organization API key |
| `GET` | `/v1/logs` | Search logs for an organization member |

See [API_SPEC.md](./API_SPEC.md) for request fields, filtering, and response
details.

## Current limitations and roadmap

- No hosted deployment, TLS termination, production secrets management, or
  production operational monitoring is included.
- No production log collector configuration or support for parsing arbitrary
  plain-text log formats is included; the demo expects JSON-lines events.
- The `pgmq` queue is populated, but no background consumer/worker is implemented.
- Dashboard refresh is periodic polling (five seconds), not a push-based stream.
- Rate limits, quotas, usage reporting, and automatic 30-day retention are not
  implemented.
- Team invitations, alerts, NLP/error grouping, LLM explanations, and billing
  are deferred.

Review [REQUIREMENTS.md](./REQUIREMENTS.md) and
[ARCHITECTURE.md](./ARCHITECTURE.md) for the design baseline and planned work.

## Security notes

- Never commit `.env`, `frontend/.env`, service-role/Secret keys, user credentials,
  or real customer logs.
- Browser configuration may contain only the Supabase URL and publishable key.
- Store organization API keys in a server-side secrets manager or environment,
  not in frontend code or a public repository.
- Do not send real customer data to the local demo without first applying an
  appropriate data-handling and redaction policy.
- The local API binds to loopback and is not reachable by remote company servers.
  Do not expose this development setup to the public internet.

## Project documents

- [Original system design and SDLC brief](./Multi-Tenant%20Log%20Monitoring%20Platform%20System%20Design%20and%20SDLC%20Rules.pdf)
- [Requirements baseline](./REQUIREMENTS.md)
- [Architecture](./ARCHITECTURE.md)
- [API contract](./API_SPEC.md)

## License

No license has been added yet. Contact the repository owner before reusing or
redistributing this project.
