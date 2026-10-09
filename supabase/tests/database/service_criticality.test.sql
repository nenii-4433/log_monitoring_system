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
values
    (
        '21000000-0000-4000-8000-000000000001',
        'authenticated',
        'authenticated',
        'criticality-owner@example.invalid',
        '',
        now(),
        now(),
        now()
    ),
    (
        '21000000-0000-4000-8000-000000000002',
        'authenticated',
        'authenticated',
        'criticality-member@example.invalid',
        '',
        now(),
        now(),
        now()
    ),
    (
        '21000000-0000-4000-8000-000000000003',
        'authenticated',
        'authenticated',
        'criticality-outsider@example.invalid',
        '',
        now(),
        now(),
        now()
    );

insert into public.organizations (id, name)
values
    ('22000000-0000-4000-8000-000000000001', 'Criticality Test A'),
    ('22000000-0000-4000-8000-000000000002', 'Criticality Test B');

insert into public.organization_members (organization_id, user_id, role)
values
    (
        '22000000-0000-4000-8000-000000000001',
        '21000000-0000-4000-8000-000000000001',
        'owner'
    ),
    (
        '22000000-0000-4000-8000-000000000001',
        '21000000-0000-4000-8000-000000000002',
        'member'
    );

select ok(
    not has_function_privilege(
        'authenticated',
        'public.set_service_criticality(uuid,uuid,text,text)',
        'EXECUTE'
    ),
    'authenticated users cannot call service criticality mutation directly'
);

set local role service_role;

select is(
    (
        select criticality
        from public.set_service_criticality(
            '21000000-0000-4000-8000-000000000001',
            '22000000-0000-4000-8000-000000000001',
            'payments',
            'critical'
        )
    ),
    'critical',
    'organization owner sets service criticality'
);

select is(
    (
        select criticality
        from public.get_service_criticalities(
            '21000000-0000-4000-8000-000000000002',
            '22000000-0000-4000-8000-000000000001'
        )
        where service = 'payments'
    ),
    'critical',
    'organization member can read service criticality'
);

select throws_ok(
    $$
        select *
        from public.set_service_criticality(
            '21000000-0000-4000-8000-000000000002',
            '22000000-0000-4000-8000-000000000001',
            'payments',
            'high'
        )
    $$,
    '42501',
    'organization owner access required',
    'organization member cannot update service criticality'
);

select throws_ok(
    $$
        select *
        from public.get_service_criticalities(
            '21000000-0000-4000-8000-000000000003',
            '22000000-0000-4000-8000-000000000001'
        )
    $$,
    '42501',
    'organization access required',
    'non-member cannot read another organization service settings'
);

select throws_ok(
    $$
        select *
        from public.set_service_criticality(
            '21000000-0000-4000-8000-000000000001',
            '22000000-0000-4000-8000-000000000001',
            'payments',
            'urgent'
        )
    $$,
    '22023',
    'invalid service criticality',
    'invalid criticality label is rejected'
);

select * from finish();
rollback;
