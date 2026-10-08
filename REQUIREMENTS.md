# Multi-Tenant Log Monitoring Platform

## Requirements baseline

- Status: Draft for review
- Version: 0.1
- Source: `Multi-Tenant Log Monitoring Platform System Design and SDLC Rules.pdf`

## Product goal

Let organizations collect logs from their applications, find and understand errors,
and receive useful alerts through a shared platform that keeps each organization's
data isolated from every other organization.

## Version 1 scale

- Support 1–5 pilot organizations.
- Support up to 10,000 ingested logs per organization per day.
- Provisional peak: 10 logs per second per organization; validate this assumption
  before finalizing load-test targets.
- Expected concurrent users have not yet been agreed.
- Accept structured JSON log events only, with a maximum event size of 256 KB.
- Retain raw logs for 30 days, then automatically delete them.

## Log event contract

- Required client fields: `timestamp` (ISO 8601), `severity`, `service`, and
  `message`.
- Allowed severity values: `trace`, `debug`, `info`, `warning`, `error`, and
  `critical`.
- Optional client fields: `environment` and `attributes` (a JSON object for
  service-specific fields).
- The server derives the organization ID from the authenticated API key. Clients
  cannot choose the organization that owns an event.

## Users

- Organization owner: manages organization settings, members, and API keys; views
  logs, error groups, insights, and alerts.
- Organization member: views and searches their organization's logs, error groups,
  insights, and alerts. Member invitations are deferred for the pilot.
- Platform administrator: performs platform-level operations without exposing one
  organization's data to another.
- Log-producing application: sends logs using an organization-scoped API key.

## In-scope features

1. User signup and authentication.
2. Organization creation and membership.
3. Organization-scoped API key creation and management.
4. Log ingestion through an authenticated API, accepting structured JSON events up
   to 256 KB each.
5. Log storage, search, and filtering.
6. NLP-based log preprocessing, severity prediction, and error grouping.
7. LLM-generated explanations for error groups.
8. Email and Slack alerts.
9. A basic dashboard, including a live log stream.
10. Basic operational quotas and usage visibility. These are limits and tracking only;
    version 1 will not create paid subscriptions or charge customers.

## Out of scope for version 1

- Billing, paid subscriptions, and payment processing.
- On-premises installation.
- Custom machine-learning models for each organization.
- A mobile application.

## Technical direction from the design

- Backend, ingestion, and NLP workers: Python with FastAPI.
- Frontend: React.
- Database and authentication: Supabase with PostgreSQL.
- Tenant isolation: PostgreSQL Row Level Security (RLS), enforced and tested for
  every organization-owned data path.
- Realtime updates: Supabase Realtime.
- Queue: Supabase `pgmq` for the pilot.
- NLP: spaCy, scikit-learn, and/or sentence-transformers as justified by evaluation.
- LLM explanations are deferred until ingestion and search work; select a provider
  before implementing that later milestone.
- Infrastructure: Docker, Nginx, and GitHub Actions.

## Acceptance targets

- Dashboard loads in under 2 seconds. The measurement method and percentile still
  need to be defined.
- Critical-severity recall is above 90% on an agreed, labeled evaluation dataset.
- Isolation tests show zero cross-tenant reads, writes, or alert triggers.
- Ingestion supports 10,000 logs per organization per day and the provisional peak
  of 10 logs per second per organization.
- Raw logs are automatically deleted after 30 days.
- API inputs are validated, and secrets are not committed to source control or
  written to logs.
- API keys are stored hashed and scoped to their owning organization.

## Open questions for detailed design

1. How many concurrent users should the pilot support?
2. Which plan tiers and quota rules should the pilot enforce?
3. Which email and Slack delivery setup should the pilot use?
4. What should the first NLP evaluation dataset contain, and who labels it?
5. How should dashboard load time be measured (for example, p95 on a defined
   dataset and environment)?

## First delivery milestones

1. Finalize detailed design decisions, tenant-aware database schema, and API
   contract.
2. Build authentication, organization membership, and RLS isolation tests.
3. Add API keys, ingestion, queueing, and log storage.
4. Add search, dashboard, NLP, explanations, and alerts in testable increments.
5. Complete integration, isolation, NLP, and load testing before pilot deployment.
