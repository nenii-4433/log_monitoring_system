create or replace function public.create_organization_for_user(
    p_user_id uuid,
    p_name text
)
returns table (
    id uuid,
    name text,
    role text,
    created_at timestamptz
)
language plpgsql
security invoker
set search_path = ''
as $function$
declare
    v_name text := pg_catalog.btrim(p_name);
    v_organization_id uuid;
    v_created_at timestamptz := pg_catalog.now();
begin
    if p_user_id is null then
        raise exception using
            errcode = '22023',
            message = 'user_id is required';
    end if;

    if v_name is null or pg_catalog.char_length(v_name) not between 1 and 120 then
        raise exception using
            errcode = '22023',
            message = 'name must be between 1 and 120 characters';
    end if;

    insert into public.organizations (name, created_at, updated_at)
    values (v_name, v_created_at, v_created_at)
    returning organizations.id, organizations.created_at
    into v_organization_id, v_created_at;

    insert into public.organization_members (
        organization_id,
        user_id,
        role,
        created_at
    )
    values (
        v_organization_id,
        p_user_id,
        'owner',
        v_created_at
    );

    return query
    select v_organization_id, v_name, 'owner'::text, v_created_at;
end;
$function$;

revoke all on function public.create_organization_for_user(uuid, text)
    from PUBLIC, anon, authenticated;

grant execute on function public.create_organization_for_user(uuid, text)
    to service_role;