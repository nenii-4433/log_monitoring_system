# Multi-Tenant Log Monitoring System

A local MVP for collecting structured application logs in organization-scoped
workspaces. The project includes a FastAPI ingestion/search API, Supabase Auth and
PostgreSQL schema, and a React dashboard for managing organizations, API keys, and
searching logs.

> **Project status:** Working local development MVP. Sign-in, organization and
> API-key management, log ingestion/search, and asynchronous severity prediction
> have been exercised locally. The automated Python suite passed 90 tests, and
> live log checks produced INFO, WARNING, and ERROR predictions. This project is
> not production-ready and has not been deployed as a hosted service.

## Features

- Supabase Auth sign-up and sign-in.
- Organization creation and membership-aware organization listing.
- Owner-only API key creation, listing, and revocation. Plaintext keys are shown
  only once; stored keys are hashed.
- Structured JSON log ingestion, with organization identity derived from the
  API key rather than supplied by the client.
- Optional producer severity stored separately from system-predicted severity;
  logs show `pending`, `complete`, or `failed` prediction status.
- Organization membership-checked log search with time, severity, service, and
  environment filters and cursor pagination.
- Asynchronous severity prediction through a PostgreSQL `pgmq` queue and a
  separately run worker, with bounded retries and visible failures.
- Layered severity evaluation using deterministic rules, context signals, an
  approved-example NLP classifier when training data is ready, and a confidence-
  gated local Ollama LLM fallback.
- Prediction method, confidence, and reason shown with each processed log.
- Owner-managed, organization-specific service criticality settings used by
  prediction context.
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
          |                              |
          |                              v
          |                      Severity worker
          |                       /     |      \
          |                   rules   NLP/context  Ollama
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

The queue is consumed by a separately run local severity worker. Dashboard
updates use five-second polling, not Supabase Realtime push.

## End-to-end working flow

1. A user signs up or signs in through Supabase Auth and creates or selects an
   organization in the React dashboard.
2. An organization owner creates an ingestion API key. The plaintext key is
   displayed once; the backend stores its SHA-256 hash and a non-secret prefix.
3. A log source sends one JSON event to `POST /v1/logs` with the API key as a
   bearer token. The event must include a timezone-aware timestamp, service, and
   message. Producer severity is optional.
4. FastAPI validates the event, resolves the organization from the API key
   rather than trusting a client-supplied organization ID, and asks PostgreSQL
   to store the log and enqueue a `pgmq` message atomically. The producer's
   optional severity is saved as `source_severity`; predicted `severity` begins
   as null with `prediction_status` set to `pending`.
5. The separately running severity worker claims queued logs through restricted
   database RPC functions. It evaluates deterministic message rules, an
   approved-data-only NLP classifier when enough training examples are approved,
   and organization-scoped context such as recent error spikes, new message
   templates, service criticality, and escalation.
6. If layers disagree, are uncertain, have no decision, or context warrants
   another review, the worker asks the local Ollama model for structured JSON.
   It validates the returned severity, confidence, and reason before accepting
   the prediction. Log messages are treated as untrusted input; log content is
   sent only to the local Ollama instance, not a hosted LLM.
7. The worker saves the predicted severity, confidence, reason, and method.
   Inference failures are retried up to three attempts; exhausted items become
   visibly `failed` rather than receiving a fabricated severity.
8. The dashboard searches only logs the signed-in user is authorized to view,
   refreshes the newest results every five seconds, and displays the prediction
   separately from the optional source label.

The main API entry point is `app.main`; the worker is a separate process started
with `python -m app.severity_worker`. Both need the local Supabase services
running. Ollama is required for the uncertain-case fallback; deterministic rules
can still handle cases that do not require that fallback.

## Technologies used

| Area | Technologies | Role |
| --- | --- | --- |
| API/backend | Python 3.11+, FastAPI, Pydantic, Uvicorn, HTTPX | Validate and ingest log events, serve authenticated dashboard APIs, and call Supabase/Ollama. |
| Database and auth | Supabase Auth, PostgreSQL, SQL migrations, `pgmq` | User sessions, tenant-scoped data, durable log storage, and asynchronous queueing through restricted RPCs. |
| Severity prediction | Python rules, scikit-learn (TF-IDF + Logistic Regression), Ollama with `qwen3:4b` | Layered predictions with a local structured-output LLM fallback. |
| Dashboard | React 19, TypeScript 5.9, Vite 7, `@supabase/supabase-js` | Sign-in, organization/API-key management, service criticality, and log search/results. |
| Local development | Docker Desktop, Supabase CLI, PowerShell | Run the local Supabase stack and development services on Windows. |
| Verification | pytest, Supabase database tests, TypeScript/Vite build | Backend, database, and frontend checks. |

The dependency manifests are `requirements.txt` and `frontend/package.json`.
The exact installed versions can differ from the compatible version ranges in
those manifests.

## Code map

| File or folder | Responsibility |
| --- | --- |
| `app/main.py` | FastAPI routes for health, organizations, service criticality, API keys, log ingestion, and member-authorized search. |
| `app/schemas.py` | Pydantic log-event validation, including optional source severity and timezone-aware timestamps. |
| `app/auth.py` | Supabase access-token validation for dashboard requests. |
| `app/severity_worker.py` | Queue consumer, prediction-layer orchestration, bounded retries, and prediction persistence. |
| `app/severity.py` | Deterministic severity rules and optional producer-severity evidence. |
| `app/severity_context.py` | Error-spike, template-novelty, service-criticality, and escalation signals. |
| `app/severity_nlp.py` | Approved-example loading, message normalization, and TF-IDF/logistic-regression classifier. |
| `app/llm_severity.py` | Local-only Ollama request, fallback gate, structured JSON validation, and result parsing. |
| `supabase/migrations/` | Database schema, tenant controls, queue functions, and prediction/service-setting RPCs. |
| `frontend/src/App.tsx` | Dashboard screens and log/prediction presentation. |
| `frontend/src/lib/api.ts` | Typed frontend HTTP API calls. |
| `demo/` | Example event generator and JSON-lines file follower for local ingestion testing. |
| `tests/`, `supabase/tests/database/` | Python unit/integration and PostgreSQL database tests. |

## Severity prediction

The prediction pipeline is implemented end-to-end. Ingestion accepts an
optional source severity and stores it separately from the nullable predicted
severity; the dashboard shows `pending` until a worker fills the prediction.
The layers are connected by `app/severity_worker.py`: deterministic rules,
an NLP classifier trained only on approved examples, context signals, and a
confidence-gated local LLM fallback. Ingestion still accepts logs immediately;
the worker processes queued events asynchronously. The predicted label set is
`trace`, `debug`, `info`, `warning`, `error`, and `critical`; any severity
supplied by a log producer is optional evidence rather than the answer.

An initial TF-IDF/logistic-regression NLP classifier is available in
`app/severity_nlp.py`. It trains only on examples explicitly marked `approved`
in `data/severity_seed.jsonl` and requires at least two approved examples per
severity. Its probabilities are not calibrated accuracy measurements, and the
classifier must have at least two approved examples per severity before the
worker can use it. With the supplied draft-only seed dataset, the worker starts
without an NLP classifier and logs that state; it never trains on drafts.

The initial context evaluator is available in `app/severity_context.py`. Its
starter spike signal is at least five similar errors in the current five-minute
window and at least three times the count in the previous five-minute window.
It also uses organization-specific service criticality, template novelty, and
an escalating-sequence signal. Unconfigured services are treated as `normal`.

The local LLM fallback client is available in `app/llm_severity.py`. It calls
Ollama on a loopback address only, defaults to `qwen3:4b`, requests a constrained
JSON result, and is gated on layer disagreement, low confidence, missing
decisions, or context signals. Install/start local Ollama and pull the configured
model before running the worker. LLM requests allow up to two minutes for local
inference and keep the model loaded for five minutes. The worker retries failed
inference up to three times, then records a visible failed prediction without
substituting a fake label.

Install Ollama locally, then pull the configured model:

```powershell
ollama pull qwen3:4b
```

Keep Ollama running locally. After starting FastAPI, run the prediction worker
in its own PowerShell terminal:

```powershell
.\.venv\Scripts\python.exe -m app.severity_worker
```

Set `OLLAMA_URL`, `OLLAMA_MODEL`, and `SEVERITY_WORKER_POLL_SECONDS` in `.env` if
you need to override their defaults. Service criticality can be managed in the
dashboard by organization owners; members can view the settings.

`data/severity_seed.jsonl` contains synthetic draft examples for all six labels.
They are starting points for review, not validated training data. Each example
must be reviewed against these definitions and marked approved before being used
to train or evaluate a model:

- `trace`: very fine-grained events that show individual execution steps.
- `debug`: diagnostic state or details useful for troubleshooting.
- `info`: expected behavior or successful operations worth recording.
- `warning`: a risk or degradation exists, but the operation/service continues.
- `error`: an operation failed, but the wider service is still operating.
- `critical`: a core or widespread failure, severe data loss, or confirmed
  high-impact security incident.

Judge `warning`, `error`, and `critical` primarily by impact and scope, not by
keywords alone. A producer-supplied label is optional evidence and can be
overruled. Mark reviewed examples by changing their `review_status` from
`draft` to `approved`; keep unreviewed examples out of training and evaluation.
These examples do not establish production accuracy.

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
| `GET` | `/v1/organizations/{organization_id}/service-criticalities` | List service importance settings |
| `PUT` | `/v1/organizations/{organization_id}/service-criticalities` | Set service importance (owner only) |
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
- Dashboard refresh is periodic polling (five seconds), not a push-based stream.
- Rate limits, quotas, usage reporting, and automatic 30-day retention are not
  implemented.
- Team invitations, alert rules/delivery, batch ingestion, error grouping, and
  billing are deferred. The NLP classifier remains unavailable until reviewed
  examples are approved for every severity; the supplied seed examples are drafts.

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
