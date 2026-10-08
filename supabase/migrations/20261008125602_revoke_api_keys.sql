create or replace function public.revoke_api_key_for_owner(
    p_user_id uuid,
    p_organization_id uuid,
    p_key_id uuid
)
returns boolean
language plpgsql
security invoker
set search_path = ''
as $function$
begin
    if p_user_id is null
       or p_organization_id is null
       or p_key_id is null then
        raise exception using
            errcode = '22023',
            message = 'user, organization, and key are required';
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

    update public.api_keys as api_key
    set revoked_at = coalesce(api_key.revoked_at, pg_catalog.now())
    where api_key.id = p_key_id
      and api_key.organization_id = p_organization_id;

    return found;
end;
$function$;

revoke all on function public.revoke_api_key_for_owner(uuid, uuid, uuid)
    from PUBLIC, anon, authenticated;

grant execute on function public.revoke_api_key_for_owner(uuid, uuid, uuid)
    to service_role;