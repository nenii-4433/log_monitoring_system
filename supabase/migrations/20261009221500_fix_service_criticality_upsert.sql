create or replace function public.set_service_criticality(
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
    insert into public.organization_service_settings as settings (
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
    on conflict on constraint organization_service_settings_pkey
    do update set
        criticality = excluded.criticality,
        updated_at = excluded.updated_at
    returning settings.service, settings.criticality, settings.updated_at;
end;
$function$;

revoke all on function public.set_service_criticality(uuid, uuid, text, text)
    from PUBLIC, anon, authenticated;

grant execute on function public.set_service_criticality(uuid, uuid, text, text)
    to service_role;
