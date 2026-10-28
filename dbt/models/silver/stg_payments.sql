-- Silver: one clean row per payment. payment_date text -> real DATE.
with ranked as (
    select *, row_number() over (partition by payment_id order by ingested_at desc) as rn
    from {{ source('bronze', 'payments') }}
)

select
    payment_id,
    customer_id,
    cast(payment_date as date) as payment_date,
    amount,
    method,
    status
from ranked
where rn = 1
