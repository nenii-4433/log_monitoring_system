begin;

select plan(9);

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
        '11000000-0000-4000-8000-000000000001',
        'authenticated',
        'authenticated',
        'search-member-a@example.invalid',
        '',
        now(),
        now(),
        now()
    ),
    (
        '11000000-0000-4000-8000-000000000002',
        'authenticated',
        'authenticated',
        'search-member-b@example.invalid',
        '',
        now(),
        now(),
        now()
    );

insert into public.organizations (id, name)
values
    ('12000000-0000-4000-8000-000000000001', 'Search Test Org A'),
    ('12000000-0000-4000-8000-000000000002', 'Search Test Org B');

insert into public.organization_members (organization_id, user_id, role)
values
    (
        '12000000-0000-4000-8000-000000000001',
        '11000000-0000-4000-8000-000000000001',
        'member'
    ),
    (
        '12000000-0000-4000-8000-000000000002',
        '11000000-0000-4000-8000-000000000002',
        'owner'
    );

insert into public.logs (
    id,
    organization_id,
    event_timestamp,
    severity,
    source_severity,
    service,
    environment,
    message,
    attributes
)
values
    (
        '13000000-0000-4000-8000-000000000001',
        '12000000-0000-4000-8000-000000000001',
        '2026-10-08T11:00:00Z',
        'error',
        'warning',
        'checkout',
        'production',
        'search test error one',
        '{"region":"west"}'::jsonb
    ),
    (
        '13000000-0000-4000-8000-000000000002',
        '12000000-0000-4000-8000-000000000001',
        '2026-10-08T10:00:00Z',
        'warning',
        'warning',
        'checkout',
        'production',
        'search test warning',
        null
    ),
    (
        '13000000-0000-4000-8000-000000000003',
        '12000000-0000-4000-8000-000000000001',
        '2026-10-08T09:00:00Z',
        'error',
        'error',
        'worker',
        'staging',
        'search test error two',
        null
    ),
    (
        '13000000-0000-4000-8000-000000000004',
        '12000000-0000-4000-8000-000000000002',
        '2026-10-08T12:00:00Z',
        'critical',
        'critical',
        'payments',
        'production',
        'other tenant search test',
        null
    );

select ok(
    not has_function_privilege(
        'anon',
        'public.search_logs_for_member(uuid,uuid,timestamptz,timestamptz,text[],text,text,timestamptz,uuid,integer)',
        'EXECUTE'
    ),
    'anon cannot execute the log-search function'
);

select ok(
    not has_function_privilege(
        'authenticated',
        'public.search_logs_for_member(uuid,uuid,timestamptz,timestamptz,text[],text,text,timestamptz,uuid,integer)',
        'EXECUTE'
    ),
    'authenticated users cannot execute the privileged log-search function'
);

set local role service_role;

select is(
    (
        select count(*)::integer
        from public.search_logs_for_member(
            '11000000-0000-4000-8000-000000000001',
            '12000000-0000-4000-8000-000000000001'
        )
    ),
    3,
    'member can search all logs in their organization'
);

select is(
    (
        select count(*)::integer
        from public.search_logs_for_member(
            '11000000-0000-4000-8000-000000000001',
            '12000000-0000-4000-8000-000000000001',
            p_severities => array['error']::text[],
            p_service => 'checkout',
            p_environment => 'production'
        )
    ),
    1,
    'severity, service, and environment filters are applied together'
);

select is(
    (
        select source_severity
        from public.search_logs_for_member(
            '11000000-0000-4000-8000-000000000001',
            '12000000-0000-4000-8000-000000000001'
        )
        where id = '13000000-0000-4000-8000-000000000001'
    ),
    'warning',
    'search returns source severity separately from predicted severity'
);

select is(
    (
        select count(*)::integer
        from public.search_logs_for_member(
            '11000000-0000-4000-8000-000000000001',
            '12000000-0000-4000-8000-000000000001',
            p_before_timestamp => '2026-10-08T10:00:00Z',
            p_before_id => '13000000-0000-4000-8000-000000000002'
        )
    ),
    1,
    'cursor returns only rows strictly after the cursor in descending order'
);

select throws_ok(
    $$
        select *
        from public.search_logs_for_member(
            '11000000-0000-4000-8000-000000000001',
            '12000000-0000-4000-8000-000000000002'
        )
    $$,
    '42501',
    'organization access required',
    'non-member cannot search another organization'
);

select throws_ok(
    $$
        select *
        from public.search_logs_for_member(
            '11000000-0000-4000-8000-000000000001',
            '12000000-0000-4000-8000-000000000001',
            p_limit => 102
        )
    $$,
    '22023',
    'limit must be between 1 and 101',
    'search limit cannot exceed 101 rows'
);

select throws_ok(
    $$
        select *
        from public.search_logs_for_member(
            '11000000-0000-4000-8000-000000000001',
            '12000000-0000-4000-8000-000000000001',
            p_from => '2026-10-08T12:00:00Z',
            p_to => '2026-10-08T11:00:00Z'
        )
    $$,
    '22023',
    'from must be earlier than or equal to to',
    'reversed time range is rejected'
);

select * from finish();
rollback;
