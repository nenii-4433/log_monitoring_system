begin;

select plan(6);

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
values (
    '50000000-0000-4000-8000-000000000001',
    'authenticated',
    'authenticated',
    'organization-test-user@example.invalid',
    '',
    now(),
    now(),
    now()
);

select ok(
    not has_function_privilege(
        'anon',
        'public.create_organization_for_user(uuid,text)',
        'EXECUTE'
    ),
    'anon cannot execute the organization creation function'
);

select ok(
    not has_function_privilege(
        'authenticated',
        'public.create_organization_for_user(uuid,text)',
        'EXECUTE'
    ),
    'authenticated users cannot execute the organization creation function'
);

set local role service_role;

select is(
    (
        select count(*)::integer
        from public.create_organization_for_user(
            '50000000-0000-4000-8000-000000000001',
            'Organization Test'
        )
    ),
    1,
    'the function returns one created organization'
);

select is(
    (
        select count(*)::integer
        from public.organizations
        where name = 'Organization Test'
    ),
    1,
    'the organization was created'
);

select is(
    (
        select role
        from public.organization_members
        where user_id = '50000000-0000-4000-8000-000000000001'
    ),
    'owner',
    'the user receives the owner membership'
);

select throws_ok(
    $$
        select *
        from public.create_organization_for_user(
            '50000000-0000-4000-8000-000000000001',
            '   '
        )
    $$,
    '22023',
    'name must be between 1 and 120 characters',
    'blank organization names are rejected'
);

select * from finish();
rollback;