create extension if not exists pgmq;

select pgmq.create('log_processing');

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
