alter table public.logs
    rename column severity to source_severity;

alter table public.logs
    alter column source_severity drop not null;

alter table public.logs
    add column severity text
    check (severity in ('trace', 'debug', 'info', 'warning', 'error', 'critical'));

drop index public.logs_org_severity_time_idx;
create index logs_org_severity_time_idx
    on public.logs (organization_id, severity, event_timestamp desc);

create or replace function public.ingest_log_for_api_key(
    p_key_prefix text,
    p_secret_hash text,
    p_event_timestamp timestamptz,
    p_severity text,
    p_service text,
    p_environment text,
    p_message text,
    p_attributes jsonb
)
returns table (
    id uuid,
    accepted_at timestamptz
)
language plpgsql
security invoker
set search_path = ''
as $function$
declare
    v_key_id uuid;
    v_organization_id uuid;
    v_log_id uuid;
    v_received_at timestamptz;
begin
    if p_key_prefix is null
       or pg_catalog.char_length(p_key_prefix) not between 8 and 32
       or p_secret_hash is null
       or p_secret_hash !~ '^[0-9a-f]{64}$' then
        raise exception using
            errcode = '28000',
            message = 'invalid API key';
    end if;

    select api_key.id, api_key.organization_id
    into v_key_id, v_organization_id
    from public.api_keys as api_key
    where api_key.key_prefix = p_key_prefix
      and api_key.secret_hash = p_secret_hash
      and api_key.revoked_at is null
    for update;

    if v_key_id is null then
        raise exception using
            errcode = '28000',
            message = 'invalid API key';
    end if;

    update public.api_keys as api_key
    set last_used_at = pg_catalog.now()
    where api_key.id = v_key_id;

    insert into public.logs (
        organization_id,
        event_timestamp,
        source_severity,
        severity,
        service,
        environment,
        message,
        attributes
    )
    values (
        v_organization_id,
        p_event_timestamp,
        p_severity,
        null,
        p_service,
        p_environment,
        p_message,
        p_attributes
    )
    returning logs.id, logs.received_at
    into v_log_id, v_received_at;

    perform pgmq.send(
        'log_processing',
        pg_catalog.jsonb_build_object(
            'log_id', v_log_id,
            'organization_id', v_organization_id
        )
    );

    return query
    select v_log_id, v_received_at;
end;
$function$;

revoke all on function public.ingest_log_for_api_key(
    text,
    text,
    timestamptz,
    text,
    text,
    text,
    text,
    jsonb
) from PUBLIC, anon, authenticated;

grant execute on function public.ingest_log_for_api_key(
    text,
    text,
    timestamptz,
    text,
    text,
    text,
    text,
    jsonb
) to service_role;

drop function public.search_logs_for_member(
    uuid,
    uuid,
    timestamptz,
    timestamptz,
    text[],
    text,
    text,
    timestamptz,
    uuid,
    integer
);

create function public.search_logs_for_member(
    p_user_id uuid,
    p_organization_id uuid,
    p_from timestamptz default null,
    p_to timestamptz default null,
    p_severities text[] default null,
    p_service text default null,
    p_environment text default null,
    p_before_timestamp timestamptz default null,
    p_before_id uuid default null,
    p_limit integer default 51
)
returns table (
    id uuid,
    event_timestamp timestamptz,
    received_at timestamptz,
    severity text,
    source_severity text,
    service text,
    environment text,
    message text,
    attributes jsonb
)
language plpgsql
security invoker
set search_path = ''
as $function$
begin
    if p_user_id is null or p_organization_id is null then
        raise exception using
            errcode = '22023',
            message = 'user and organization are required';
    end if;

    if p_limit is null or p_limit not between 1 and 101 then
        raise exception using
            errcode = '22023',
            message = 'limit must be between 1 and 101';
    end if;

    if (p_before_timestamp is null) <> (p_before_id is null) then
        raise exception using
            errcode = '22023',
            message = 'both cursor values must be provided together';
    end if;

    if p_from is not null and p_to is not null and p_from > p_to then
        raise exception using
            errcode = '22023',
            message = 'from must be earlier than or equal to to';
    end if;

    if not exists (
        select 1
        from public.organization_members as membership
        where membership.organization_id = p_organization_id
          and membership.user_id = p_user_id
    ) then
        raise exception using
            errcode = '42501',
            message = 'organization access required';
    end if;

    return query
    select
        log_entry.id,
        log_entry.event_timestamp,
        log_entry.received_at,
        log_entry.severity,
        log_entry.source_severity,
        log_entry.service,
        log_entry.environment,
        log_entry.message,
        log_entry.attributes
    from public.logs as log_entry
    where log_entry.organization_id = p_organization_id
      and (p_from is null or log_entry.event_timestamp >= p_from)
      and (p_to is null or log_entry.event_timestamp <= p_to)
      and (
          p_severities is null
          or log_entry.severity = any (p_severities)
      )
      and (p_service is null or log_entry.service = p_service)
      and (p_environment is null or log_entry.environment = p_environment)
      and (
          p_before_timestamp is null
          or (log_entry.event_timestamp, log_entry.id)
             < (p_before_timestamp, p_before_id)
      )
    order by log_entry.event_timestamp desc, log_entry.id desc
    limit p_limit;
end;
$function$;

revoke all on function public.search_logs_for_member(
    uuid,
    uuid,
    timestamptz,
    timestamptz,
    text[],
    text,
    text,
    timestamptz,
    uuid,
    integer
) from PUBLIC, anon, authenticated;

grant execute on function public.search_logs_for_member(
    uuid,
    uuid,
    timestamptz,
    timestamptz,
    text[],
    text,
    text,
    timestamptz,
    uuid,
    integer
) to service_role;
