create or replace function public.list_api_keys_for_owner(
    p_user_id uuid,
    p_organization_id uuid
)
returns table (
    id uuid,
    name text,
    key_prefix text,
    created_at timestamptz,
    last_used_at timestamptz,
    revoked_at timestamptz
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

    if not exists (
        select 1
        from public.organization_members as membership
        where membership.organization_id = p_organization_id
          and membership.user_id = p_user_id
          and membership.role = 'owner'
    ) then
        raise exception using
            errcode = '42501',
            message = 'owner access required';
    end if;

    return query
    select
        api_key.id,
        api_key.name,
        api_key.key_prefix,
        api_key.created_at,
        api_key.last_used_at,
        api_key.revoked_at
    from public.api_keys as api_key
    where api_key.organization_id = p_organization_id
    order by api_key.created_at desc, api_key.id;
end;
$function$;

revoke all on function public.list_api_keys_for_owner(uuid, uuid)
    from PUBLIC, anon, authenticated;

grant execute on function public.list_api_keys_for_owner(uuid, uuid)
    to service_role;