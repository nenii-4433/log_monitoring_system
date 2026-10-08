begin;

select plan(7);

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
        '10000000-0000-4000-8000-000000000001',
        'authenticated',
        'authenticated',
        'tenant-test-owner-a@example.invalid',
        '',
        now(),
        now(),
        now()
    ),
    (
        '10000000-0000-4000-8000-000000000002',
        'authenticated',
        'authenticated',
        'tenant-test-member-a@example.invalid',
        '',
        now(),
        now(),
        now()
    ),
    (
        '10000000-0000-4000-8000-000000000003',
        'authenticated',
        'authenticated',
        'tenant-test-owner-b@example.invalid',
        '',
        now(),
        now(),
        now()
    );

insert into public.organizations (id, name)
values
    ('20000000-0000-4000-8000-000000000001', 'Tenant Test A'),
    ('20000000-0000-4000-8000-000000000002', 'Tenant Test B');

insert into public.organization_members (organization_id, user_id, role)
values
    (
        '20000000-0000-4000-8000-000000000001',
        '10000000-0000-4000-8000-000000000001',
        'owner'
    ),
    (
        '20000000-0000-4000-8000-000000000001',
        '10000000-0000-4000-8000-000000000002',
        'member'
    ),
    (
        '20000000-0000-4000-8000-000000000002',
        '10000000-0000-4000-8000-000000000003',
        'owner'
    );

insert into public.api_keys (
    id,
    organization_id,
    name,
    key_prefix,
    secret_hash
)
values
    (
        '30000000-0000-4000-8000-000000000001',
        '20000000-0000-4000-8000-000000000001',
        'Tenant A test key',
        'test-prefix-a',
        'not-a-real-secret-hash'
    ),
    (
        '30000000-0000-4000-8000-000000000002',
        '20000000-0000-4000-8000-000000000002',
        'Tenant B test key',
        'test-prefix-b',
        'not-a-real-secret-hash'
    );

insert into public.logs (
    id,
    organization_id,
    event_timestamp,
    severity,
    service,
    message
)
values
    (
        '40000000-0000-4000-8000-000000000001',
        '20000000-0000-4000-8000-000000000001',
        now(),
        'error',
        'tenant-test-service',
        'Tenant A test log'
    ),
    (
        '40000000-0000-4000-8000-000000000002',
        '20000000-0000-4000-8000-000000000002',
        now(),
        'error',
        'tenant-test-service',
        'Tenant B test log'
    );

set local role authenticated;
select set_config(
    'request.jwt.claim.sub',
    '10000000-0000-4000-8000-000000000001',
    true
);

select is(
    (select count(*)::integer from public.organizations),
    1,
    'owner sees only their organization'
);
select is(
    (select count(*)::integer from public.logs),
    1,
    'owner sees only logs belonging to their organization'
);
select is(
    (select count(id)::integer from public.api_keys),
    1,
    'owner sees only API key metadata for their organization'
);
select ok(
    not has_column_privilege(
        'authenticated',
        'public.api_keys',
        'secret_hash',
        'SELECT'
    ),
    'authenticated users cannot read API key hashes'
);
select ok(
    not has_table_privilege('authenticated', 'public.logs', 'INSERT'),
    'authenticated users cannot insert logs directly'
);

select set_config(
    'request.jwt.claim.sub',
    '10000000-0000-4000-8000-000000000002',
    true
);
select is(
    (select count(*)::integer from public.logs),
    1,
    'member sees logs belonging to their organization'
);
select is(
    (select count(id)::integer from public.api_keys),
    0,
    'member cannot see API key metadata'
);

select * from finish();
rollback;
