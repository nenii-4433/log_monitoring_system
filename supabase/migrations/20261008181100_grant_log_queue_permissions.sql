grant usage on schema pgmq to service_role;

grant execute on function pgmq.send(text, jsonb, integer)
    to service_role;