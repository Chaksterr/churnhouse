-- Silver: one clean row per ticket. created_at text -> real DATE.
with ranked as (
    select *, row_number() over (partition by ticket_id order by ingested_at desc) as rn
    from {{ source('bronze', 'support_tickets') }}
)

select
    ticket_id,
    customer_id,
    category,
    status,
    cast(created_at as date) as created_date,
    satisfaction_score
from ranked
where rn = 1
