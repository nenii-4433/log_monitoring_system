alter table public.logs
    add column prediction_status text not null default 'pending'
        check (prediction_status in ('pending', 'complete', 'failed')),
    add column prediction_confidence double precision
        check (
            prediction_confidence is null
            or prediction_confidence between 0 and 1
        ),
    add column prediction_reason text,
    add column prediction_method text,
    add column prediction_error text;

create table public.organization_service_settings (
    organization_id uuid not null
        references public.organizations (id) on delete cascade,
    service text not null check (char_length(service) between 1 and 120),
    criticality text not null
        check (criticality in ('low', 'normal', 'high', 'critical')),
    updated_at timestamptz not null default now(),
    primary key (organization_id, service)
);

alter table public.organization_service_settings enable row level security;
revoke all on public.organization_service_settings from PUBLIC, anon, authenticated;

create function public.get_service_criticalities(
    p_user_id uuid,
    p_organization_id uuid
)
returns table (service text, criticality text)
language plpgsql
security definer
set search_path = ''
as $function$
begin
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
    select setting.service, setting.criticality
    from public.organization_service_settings as setting
    where setting.organization_id = p_organization_id
    order by setting.service;
end;
$function$;

create function public.set_service_criticality(
    p_user_id uuid,
    p_organization_id uuid,
    p_service text,
    p_criticality text
)
returns table (service text, criticality text, updated_at timestamptz)
language plpgsql
security definer
set search_path = ''
as $function$
begin
    if p_service is null
       or pg_catalog.char_length(pg_catalog.btrim(p_service)) not between 1 and 120
       or p_criticality is null
       or p_criticality not in ('low', 'normal', 'high', 'critical') then
        raise exception using
            errcode = '22023',
            message = 'invalid service criticality';
    end if;

    if not exists (
        select 1
        from public.organization_members as membership
        where membership.organization_id = p_organization_id
          and membership.user_id = p_user_id
          and membership.role = 'owner'
    ) then
        raise exception using
            errcode = '42501',
            message = 'organization owner access required';
    end if;

    return query
    insert into public.organization_service_settings as setting (
        organization_id,
        service,
        criticality,
        updated_at
    )
    values (
        p_organization_id,
        pg_catalog.btrim(p_service),
        p_criticality,
        pg_catalog.now()
    )
    on conflict (organization_id, service)
    do update set
        criticality = excluded.criticality,
        updated_at = excluded.updated_at
    returning setting.service, setting.criticality, setting.updated_at;
end;
$function$;

create function public.claim_log_for_severity_prediction()
returns table (
    message_id bigint,
    read_count integer,
    log_id uuid,
    organization_id uuid,
    event_timestamp timestamptz,
    source_severity text,
    service text,
    environment text,
    message text,
    attributes jsonb,
    recent_similar_errors bigint,
    previous_similar_errors bigint,
    template_seen_before boolean,
    service_criticality text,
    escalating_sequence boolean
)
language sql
security definer
set search_path = ''
as $function$
    with next_message as materialized (
        select queued.msg_id, queued.read_ct, queued.message
        from pgmq.read('log_processing', 30, 1) as queued
    ),
    target as (
        select
            queued.msg_id,
            queued.read_ct,
            log_entry.id,
            log_entry.organization_id,
            log_entry.event_timestamp,
            log_entry.received_at,
            log_entry.source_severity,
            log_entry.service,
            log_entry.environment,
            log_entry.message,
            log_entry.attributes,
            pg_catalog.regexp_replace(
                pg_catalog.lower(log_entry.message),
                '\m[0-9]+\M',
                '<number>',
                'g'
            ) as normalized_message
        from next_message as queued
        join public.logs as log_entry
          on log_entry.id = (queued.message ->> 'log_id')::uuid
         and log_entry.organization_id
             = (queued.message ->> 'organization_id')::uuid
    )
    select
        target.msg_id,
        target.read_ct,
        target.id,
        target.organization_id,
        target.event_timestamp,
        target.source_severity,
        target.service,
        target.environment,
        target.message,
        target.attributes,
        (
            select pg_catalog.count(*)
            from public.logs as recent
            where recent.organization_id = target.organization_id
              and recent.service = target.service
              and pg_catalog.regexp_replace(
                    pg_catalog.lower(recent.message),
                    '\m[0-9]+\M',
                    '<number>',
                    'g'
                  ) = target.normalized_message
              and recent.message ~* '(failed|failure|timeout|timed out|exception|HTTP 5[0-9][0-9]|connection refused)'
              and recent.received_at > target.received_at - interval '5 minutes'
              and recent.received_at <= target.received_at
        ),
        (
            select pg_catalog.count(*)
            from public.logs as previous
            where previous.organization_id = target.organization_id
              and previous.service = target.service
              and pg_catalog.regexp_replace(
                    pg_catalog.lower(previous.message),
                    '\m[0-9]+\M',
                    '<number>',
                    'g'
                  ) = target.normalized_message
              and previous.message ~* '(failed|failure|timeout|timed out|exception|HTTP 5[0-9][0-9]|connection refused)'
              and previous.received_at > target.received_at - interval '10 minutes'
              and previous.received_at <= target.received_at - interval '5 minutes'
        ),
        exists (
            select 1
            from public.logs as earlier
            where earlier.organization_id = target.organization_id
              and earlier.service = target.service
              and pg_catalog.regexp_replace(
                    pg_catalog.lower(earlier.message),
                    '\m[0-9]+\M',
                    '<number>',
                    'g'
                  ) = target.normalized_message
              and earlier.received_at < target.received_at
        ),
        coalesce(setting.criticality, 'normal'),
        exists (
            select 1
            from public.logs as earlier_warning
            join public.logs as later_error
              on later_error.organization_id = earlier_warning.organization_id
             and later_error.service = earlier_warning.service
             and later_error.received_at > earlier_warning.received_at
             and later_error.received_at > target.received_at - interval '5 minutes'
             and later_error.received_at <= target.received_at
             and later_error.message ~* '(failed|failure|timeout|exception|HTTP 5[0-9][0-9])'
            where earlier_warning.organization_id = target.organization_id
              and earlier_warning.service = target.service
              and earlier_warning.received_at > target.received_at - interval '5 minutes'
              and earlier_warning.received_at < target.received_at
              and earlier_warning.message ~* '(warning|degraded|latency|retrying)'
        )
    from target
    left join public.organization_service_settings as setting
      on setting.organization_id = target.organization_id
     and setting.service = target.service;
$function$;

create function public.finish_log_severity_prediction(
    p_message_id bigint,
    p_log_id uuid,
    p_status text,
    p_severity text,
    p_confidence double precision,
    p_reason text,
    p_method text,
    p_error text
)
returns void
language plpgsql
security definer
set search_path = ''
as $function$
begin
    if p_status = 'complete' then
        if p_severity is null
           or p_severity not in ('trace', 'debug', 'info', 'warning', 'error', 'critical')
           or p_confidence is null
           or p_confidence not between 0 and 1
           or p_reason is null
           or pg_catalog.btrim(p_reason) = ''
           or pg_catalog.char_length(p_reason) > 500
           or p_method is null
           or p_method not in ('message_rule', 'source_hint', 'nlp', 'local_llm') then
            raise exception using
                errcode = '22023',
                message = 'invalid completed prediction';
        end if;

        update public.logs
        set severity = p_severity,
            prediction_confidence = p_confidence,
            prediction_reason = p_reason,
            prediction_method = p_method,
            prediction_status = 'complete',
            prediction_error = null
        where id = p_log_id;
    elsif p_status = 'failed' then
        if p_error is null
           or pg_catalog.btrim(p_error) = ''
           or pg_catalog.char_length(p_error) > 500 then
            raise exception using
                errcode = '22023',
                message = 'prediction failure reason is required';
        end if;

        update public.logs
        set prediction_status = 'failed',
            prediction_error = p_error
        where id = p_log_id;
    else
        raise exception using
            errcode = '22023',
            message = 'invalid prediction status';
    end if;

    if not found then
        raise exception using
            errcode = 'P0002',
            message = 'log event not found';
    end if;

    if not pgmq.delete('log_processing', p_message_id) then
        raise exception using
            errcode = 'P0002',
            message = 'queue message not found';
    end if;
end;
$function$;

create function public.release_log_for_severity_retry(
    p_message_id bigint,
    p_delay_seconds integer
)
returns void
language plpgsql
security definer
set search_path = ''
as $function$
begin
    if p_delay_seconds is null or p_delay_seconds not between 1 and 300 then
        raise exception using
            errcode = '22023',
            message = 'retry delay must be between 1 and 300 seconds';
    end if;

    if not pgmq.set_vt('log_processing', p_message_id, p_delay_seconds) then
        raise exception using
            errcode = 'P0002',
            message = 'queue message not found';
    end if;
end;
$function$;

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
    prediction_status text,
    prediction_confidence double precision,
    prediction_reason text,
    prediction_method text,
    prediction_error text,
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
        log_entry.prediction_status,
        log_entry.prediction_confidence,
        log_entry.prediction_reason,
        log_entry.prediction_method,
        log_entry.prediction_error,
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

revoke all on function public.get_service_criticalities(uuid, uuid)
    from PUBLIC, anon, authenticated;
revoke all on function public.set_service_criticality(uuid, uuid, text, text)
    from PUBLIC, anon, authenticated;
revoke all on function public.claim_log_for_severity_prediction()
    from PUBLIC, anon, authenticated;
revoke all on function public.finish_log_severity_prediction(
    bigint, uuid, text, text, double precision, text, text, text
) from PUBLIC, anon, authenticated;
revoke all on function public.release_log_for_severity_retry(bigint, integer)
    from PUBLIC, anon, authenticated;
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

grant execute on function public.get_service_criticalities(uuid, uuid)
    to service_role;
grant execute on function public.set_service_criticality(uuid, uuid, text, text)
    to service_role;
grant execute on function public.claim_log_for_severity_prediction()
    to service_role;
grant execute on function public.finish_log_severity_prediction(
    bigint, uuid, text, text, double precision, text, text, text
) to service_role;
grant execute on function public.release_log_for_severity_retry(bigint, integer)
    to service_role;
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
