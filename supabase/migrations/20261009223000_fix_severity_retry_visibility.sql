create or replace function public.release_log_for_severity_retry(
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

    perform pgmq.set_vt('log_processing', p_message_id, p_delay_seconds);
    if not found then
        raise exception using
            errcode = 'P0002',
            message = 'queue message not found';
    end if;
end;
$function$;

revoke all on function public.release_log_for_severity_retry(bigint, integer)
    from PUBLIC, anon, authenticated;

grant execute on function public.release_log_for_severity_retry(bigint, integer)
    to service_role;
