create table public.organizations (
    id uuid primary key default gen_random_uuid(),
    name text not null check (char_length(name) between 1 and 120),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table public.organization_members (
    organization_id uuid not null
        references public.organizations (id) on delete cascade,
    user_id uuid not null
        references auth.users (id) on delete cascade,
    role text not null check (role in ('owner', 'member')),
    created_at timestamptz not null default now(),
    primary key (organization_id, user_id)
);

create table public.api_keys (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null
        references public.organizations (id) on delete cascade,
    name text not null check (char_length(name) between 1 and 120),
    key_prefix text not null unique,
    secret_hash text not null,
    created_at timestamptz not null default now(),
    last_used_at timestamptz,
    revoked_at timestamptz
);

create table public.logs (
    id uuid primary key default gen_random_uuid(),
    organization_id uuid not null
        references public.organizations (id) on delete cascade,
    event_timestamp timestamptz not null,
    received_at timestamptz not null default now(),
    severity text not null
        check (severity in ('trace', 'debug', 'info', 'warning', 'error', 'critical')),
    service text not null check (char_length(service) between 1 and 120),
    environment text check (
        environment is null or char_length(environment) between 1 and 120
    ),
    message text not null check (octet_length(message) between 1 and 262144),
    attributes jsonb
        check (attributes is null or jsonb_typeof(attributes) = 'object')
);

create index logs_org_event_time_idx
    on public.logs (organization_id, event_timestamp desc);

create index logs_org_severity_time_idx
    on public.logs (organization_id, severity, event_timestamp desc);

create index logs_org_service_time_idx
    on public.logs (organization_id, service, event_timestamp desc);

create index logs_org_received_time_idx
    on public.logs (organization_id, received_at);

alter table public.organizations enable row level security;
alter table public.organization_members enable row level security;
alter table public.api_keys enable row level security;
alter table public.logs enable row level security;

revoke all on public.organizations from PUBLIC, anon, authenticated;
revoke all on public.organization_members from PUBLIC, anon, authenticated;
revoke all on public.api_keys from PUBLIC, anon, authenticated;
revoke all on public.logs from PUBLIC, anon, authenticated;

grant select on public.organizations to authenticated;
grant select on public.organization_members to authenticated;
grant select (
    id,
    organization_id,
    name,
    key_prefix,
    created_at,
    last_used_at,
    revoked_at
) on public.api_keys to authenticated;
grant select on public.logs to authenticated;

create policy organizations_select_for_members
    on public.organizations
    for select
    to authenticated
    using (
        exists (
            select 1
            from public.organization_members as membership
            where membership.organization_id = organizations.id
              and membership.user_id = (select auth.uid())
        )
    );

create policy organization_members_select_self
    on public.organization_members
    for select
    to authenticated
    using (user_id = (select auth.uid()));

create policy api_keys_select_for_owners
    on public.api_keys
    for select
    to authenticated
    using (
        exists (
            select 1
            from public.organization_members as membership
            where membership.organization_id = api_keys.organization_id
              and membership.user_id = (select auth.uid())
              and membership.role = 'owner'
        )
    );

create policy logs_select_for_members
    on public.logs
    for select
    to authenticated
    using (
        exists (
            select 1
            from public.organization_members as membership
            where membership.organization_id = logs.organization_id
              and membership.user_id = (select auth.uid())
        )
    );