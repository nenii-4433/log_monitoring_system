create or replace function public.search_logs_for_member(
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