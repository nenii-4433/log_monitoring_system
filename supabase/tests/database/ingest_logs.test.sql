begin;

select plan(8);

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
    'd0000000-0000-4000-8000-000000000001',
    'authenticated',
    'authenticated',
    'ingest-log-owner@example.invalid',
    '',
    now(),
    now(),
    now()
);

insert into public.organizations (id, name)
values
    ('e0000000-0000-4000-8000-000000000001', 'Ingest Test Org A'),
    ('e0000000-0000-4000-8000-000000000002', 'Ingest Test Org B');

insert into public.organization_members (organization_id, user_id, role)
values (
    'e0000000-0000-4000-8000-000000000001',
    'd0000000-0000-4000-8000-000000000001',
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
        'f0000000-0000-4000-8000-000000000001',
        'e0000000-0000-4000-8000-000000000001',
        'Active ingestion key',
        'ingestkey001',
        repeat('e', 64)
    ),
    (
        'f0000000-0000-4000-8000-000000000002',
        'e0000000-0000-4000-8000-000000000002',
        'Revoked ingestion key',
        'ingestkey002',
        repeat('f', 64)
    );

update public.api_keys
set revoked_at = now()
where id = 'f0000000-0000-4000-8000-000000000002';

select ok(
    not has_function_privilege(
        'anon',
        'public.ingest_log_for_api_key(text,text,timestamptz,text,text,text,text,jsonb)',
        'EXECUTE'
    ),
    'anon cannot execute the log ingestion function'
);

select ok(
    not has_function_privilege(
        'authenticated',
        'public.ingest_log_for_api_key(text,text,timestamptz,text,text,text,text,jsonb)',
        'EXECUTE'
    ),
    'authenticated users cannot execute the log ingestion function'
);

set local role service_role;

select is(
    (
        select count(*)::integer
        from public.ingest_log_for_api_key(
            'ingestkey001',
            repeat('e', 64),
            '2026-10-08T09:30:00Z',
            'error',
            'checkout',
            'production',
            'valid ingestion test message',
            '{"region":"west"}'::jsonb
        )
    ),
    1,
    'valid API key accepts one log'
);

select is(
    (
        select organization_id
        from public.logs
        where message = 'valid ingestion test message'
    ),
    'e0000000-0000-4000-8000-000000000001'::uuid,
    'log tenant is derived from the API key'
);

select ok(
    (
        select last_used_at is not null
        from public.api_keys
        where id = 'f0000000-0000-4000-8000-000000000001'
    ),
    'successful ingestion updates API key last-used time'
);

reset role;

select ok(
    exists (
        select 1
        from pgmq.q_log_processing as queued
        join public.logs as stored
          on stored.id = (queued.message ->> 'log_id')::uuid
        where stored.message = 'valid ingestion test message'
          and queued.message ->> 'organization_id'
              = 'e0000000-0000-4000-8000-000000000001'
    ),
    'accepted log has a queue message tagged with its tenant'
);

select throws_ok(
    $$
        select *
        from public.ingest_log_for_api_key(
            'ingestkey001',
            repeat('a', 64),
            '2026-10-08T09:31:00Z',
            'error',
            'checkout',
            'production',
            'invalid hash test message',
            null
        )
    $$,
    '28000',
    'invalid API key',
    'incorrect API key hash is rejected'
);

select throws_ok(
    $$
        select *
        from public.ingest_log_for_api_key(
            'ingestkey002',
            repeat('f', 64),
            '2026-10-08T09:32:00Z',
            'error',
            'checkout',
            'production',
            'revoked key test message',
            null
        )
    $$,
    '28000',
    'invalid API key',
    'revoked API key is rejected'
);

select * from finish();
rollback;
