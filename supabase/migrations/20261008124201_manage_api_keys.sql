create or replace function public.create_api_key_for_owner(
    p_user_id uuid,
    p_organization_id uuid,
    p_name text,
    p_key_prefix text,
    p_secret_hash text
)
returns table (
    id uuid,
    organization_id uuid,
    name text,
    key_prefix text,
    created_at timestamptz,
    revoked_at timestamptz
)
language plpgsql
security invoker
set search_path = ''
as $function$
declare
    v_name text := pg_catalog.btrim(p_name);
    v_id uuid;
    v_created_at timestamptz := pg_catalog.now();
begin
    if p_user_id is null or p_organization_id is null then
        raise exception using
            errcode = '22023',
            message = 'user and organization are required';
    end if;

    if v_name is null or pg_catalog.char_length(v_name) not between 1 and 120 then
        raise exception using
            errcode = '22023',
            message = 'name must be between 1 and 120 characters';
    end if;

    if p_key_prefix is null
       or pg_catalog.char_length(p_key_prefix) not between 8 and 32 then
        raise exception using
            errcode = '22023',
            message = 'invalid key prefix';
    end if;

    if p_secret_hash is null or p_secret_hash !~ '^[0-9a-f]{64}$' then
        raise exception using
            errcode = '22023',
            message = 'invalid key hash';
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

    insert into public.api_keys (
        organization_id,
        name,
        key_prefix,
        secret_hash,
        created_at
    )
    values (
        p_organization_id,
        v_name,
        p_key_prefix,
        p_secret_hash,
        v_created_at
    )
    returning api_keys.id into v_id;

    return query
    select
        v_id,
        p_organization_id,
        v_name,
        p_key_prefix,
        v_created_at,
        null::timestamptz;
end;
$function$;

revoke all on function public.create_api_key_for_owner(
    uuid,
    uuid,
    text,
    text,
    text
) from PUBLIC, anon, authenticated;

grant execute on function public.create_api_key_for_owner(
    uuid,
    uuid,
    text,
    text,
    text
) to service_role;