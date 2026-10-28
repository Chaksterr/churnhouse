-- Quarantine: rows that exist in bronze but were NOT kept by Silver, with a reason.
-- Today's reason: superseded duplicate copies from the double loader run.
-- Tomorrow: new reject classes = new union branch (+ its own reason text).
with losers as (
    select 'customers' as source_table, customer_id as row_key, ingested_at from (
        select *, row_number() over (partition by customer_id order by ingested_at desc) as rn
        from {{ source('bronze', 'customers') }}
    ) x where rn > 1

    union all
    select 'support_tickets', ticket_id, ingested_at from (
        select *, row_number() over (partition by ticket_id order by ingested_at desc) as rn
        from {{ source('bronze', 'support_tickets') }}
    ) x where rn > 1

    union all
    select 'payments', payment_id, ingested_at from (
        select *, row_number() over (partition by payment_id order by ingested_at desc) as rn
        from {{ source('bronze', 'payments') }}
    ) x where rn > 1

    union all
    select 'customers_contact', customer_id, ingested_at from (
        select *, row_number() over (partition by customer_id order by ingested_at desc) as rn
        from {{ source('bronze', 'customers_contact') }}
    ) x where rn > 1
)

select source_table, row_key, ingested_at,
       'superseded copy from an earlier loader run' as reason
from losers
order by source_table, ingested_at
