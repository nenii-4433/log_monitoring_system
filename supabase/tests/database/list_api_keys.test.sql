begin;

select plan(5);

insert into auth.users (
    id,
    aud,
    role,
    email,
    encrypted_password,
    email_confirmed_at,
    created_at,
    updated_at
)
values
    (
        '80000000-0000-4000-8000-000000000001',
        'authenticated',
        'authenticated',
        'list-keys-owner@example.invalid',
        '',
        now(),
        now(),
        now()
    ),
    (
        '80000000-0000-4000-8000-000000000002',
        'authenticated',
        'authenticated',
        'list-keys-member@example.invalid',
        '',
        now(),
        now(),
        now()
    );

insert into public.organizations (id, name)
values ('90000000-0000-4000-8000-000000000001', 'List Keys Test Org');

insert into public.organization_members (organization_id, user_id, role)
values
    (
        '90000000-0000-4000-8000-000000000001',
        '80000000-0000-4000-8000-000000000001',
        'owner'
    ),
    (
        '90000000-0000-4000-8000-000000000001',
        '80000000-0000-4000-8000-000000000002',
        'member'
    );

insert into public.api_keys (
    organization_id,
    name,
    key_prefix,
    secret_hash
)
values (
    '90000000-0000-4000-8000-000000000001',
    'Metadata test key',
    'listkeys001',
    repeat('c', 64)
);

select ok(
    not has_function_privilege(
        'anon',
        'public.list_api_keys_for_owner(uuid,uuid)',
        'EXECUTE'
    ),
    'anon cannot execute the key-list function'
);

select ok(
    not has_function_privilege(
        'authenticated',
        'public.list_api_keys_for_owner(uuid,uuid)',
        'EXECUTE'
    ),
    'authenticated users cannot execute the key-list function'
);

set local role service_role;

select is(
    (
        select count(*)::integer
        from public.list_api_keys_for_owner(
            '80000000-0000-4000-8000-000000000001',
            '90000000-0000-4000-8000-000000000001'
        )
    ),
    1,
    'owner can list key metadata'
);

select throws_ok(
    $$
        select *
        from public.list_api_keys_for_owner(
            '80000000-0000-4000-8000-000000000002',
            '90000000-0000-4000-8000-000000000001'
        )
    $$,
    '42501',
    'owner access required',
    'member cannot list API keys'
);

select ok(
    pg_catalog.pg_get_function_result(
        'public.list_api_keys_for_owner(uuid,uuid)'::regprocedure
    ) not like '%secret_hash%',
    'function result does not include the stored secret hash'
);

select * from finish();
rollback;