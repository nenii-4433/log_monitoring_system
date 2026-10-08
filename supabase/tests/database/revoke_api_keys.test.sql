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
        'a0000000-0000-4000-8000-000000000001',
        'authenticated',
        'authenticated',
        'revoke-keys-owner@example.invalid',
        '',
        now(),
        now(),
        now()
    ),
    (
        'a0000000-0000-4000-8000-000000000002',
        'authenticated',
        'authenticated',
        'revoke-keys-member@example.invalid',
        '',
        now(),
        now(),
        now()
    );

insert into public.organizations (id, name)
values ('b0000000-0000-4000-8000-000000000001', 'Revoke Keys Test Org');

insert into public.organization_members (organization_id, user_id, role)
values
    (
        'b0000000-0000-4000-8000-000000000001',
        'a0000000-0000-4000-8000-000000000001',
        'owner'
    ),
    (
        'b0000000-0000-4000-8000-000000000001',
        'a0000000-0000-4000-8000-000000000002',
        'member'
    );

insert into public.api_keys (
    id,
    organization_id,
    name,
    key_prefix,
    secret_hash
)
values (
    'c0000000-0000-4000-8000-000000000001',
    'b0000000-0000-4000-8000-000000000001',
    'Revoke test key',
    'revoketest01',
    repeat('d', 64)
);

select ok(
    not has_function_privilege(
        'anon',
        'public.revoke_api_key_for_owner(uuid,uuid,uuid)',
        'EXECUTE'
    ),
    'anon cannot execute the key-revocation function'
);

select ok(
    not has_function_privilege(
        'authenticated',
        'public.revoke_api_key_for_owner(uuid,uuid,uuid)',
        'EXECUTE'
    ),
    'authenticated users cannot execute the key-revocation function'
);

set local role service_role;

select is(
    public.revoke_api_key_for_owner(
        'a0000000-0000-4000-8000-000000000001',
        'b0000000-0000-4000-8000-000000000001',
        'c0000000-0000-4000-8000-000000000001'
    ),
    true,
    'owner can revoke a key in their organization'
);

select ok(
    (
        select revoked_at is not null
        from public.api_keys
        where id = 'c0000000-0000-4000-8000-000000000001'
    ),
    'revocation timestamp is stored'
);

select is(
    public.revoke_api_key_for_owner(
        'a0000000-0000-4000-8000-000000000001',
        'b0000000-0000-4000-8000-000000000001',
        'c0000000-0000-4000-8000-000000000001'
    ),
    true,
    'repeating revocation is safe'
);

select throws_ok(
    $$
        select public.revoke_api_key_for_owner(
            'a0000000-0000-4000-8000-000000000002',
            'b0000000-0000-4000-8000-000000000001',
            'c0000000-0000-4000-8000-000000000001'
        )
    $$,
    '42501',
    'owner access required',
    'member cannot revoke an API key'
);

select is(
    public.revoke_api_key_for_owner(
        'a0000000-0000-4000-8000-000000000001',
        'b0000000-0000-4000-8000-000000000001',
        'c0000000-0000-4000-8000-000000000099'
    ),
    false,
    'nonexistent key returns false'
);

select * from finish();
rollback;