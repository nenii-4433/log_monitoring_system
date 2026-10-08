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
        '60000000-0000-4000-8000-000000000001',
        'authenticated',
        'authenticated',
        'api-key-owner@example.invalid',
        '',
        now(),
        now(),
        now()
    ),
    (
        '60000000-0000-4000-8000-000000000002',
        'authenticated',
        'authenticated',
        'api-key-member@example.invalid',
        '',
        now(),
        now(),
        now()
    );

insert into public.organizations (id, name)
values ('70000000-0000-4000-8000-000000000001', 'API Key Test Org');

insert into public.organization_members (organization_id, user_id, role)
values
    (
        '70000000-0000-4000-8000-000000000001',
        '60000000-0000-4000-8000-000000000001',
        'owner'
    ),
    (
        '70000000-0000-4000-8000-000000000001',
        '60000000-0000-4000-8000-000000000002',
        'member'
    );

select ok(
    not has_function_privilege(
        'anon',
        'public.create_api_key_for_owner(uuid,uuid,text,text,text)',
        'EXECUTE'
    ),
    'anon cannot execute the API-key creation function'
);

select ok(
    not has_function_privilege(
        'authenticated',
        'public.create_api_key_for_owner(uuid,uuid,text,text,text)',
        'EXECUTE'
    ),
    'authenticated users cannot execute the API-key creation function'
);

set local role service_role;

select is(
    (
        select count(*)::integer
        from public.create_api_key_for_owner(
            '60000000-0000-4000-8000-000000000001',
            '70000000-0000-4000-8000-000000000001',
            'Owner key',
            'testprefix1',
            repeat('a', 64)
        )
    ),
    1,
    'owner can create an API key'
);

select throws_ok(
    $$
        select *
        from public.create_api_key_for_owner(
            '60000000-0000-4000-8000-000000000002',
            '70000000-0000-4000-8000-000000000001',
            'Member key',
            'testprefix2',
            repeat('b', 64)
        )
    $$,
    '42501',
    'owner access required',
    'member cannot create an API key'
);

select is(
    (
        select count(*)::integer
        from public.api_keys
        where organization_id = '70000000-0000-4000-8000-000000000001'
    ),
    1,
    'only the owner key was stored'
);

select * from finish();
rollback;