-- GOLD: money story by month. Revenue = money actually received (succeeded).
-- billed-attempted-but-failed stays visible so the gap is honest.

select
    date_trunc('month', payment_date) as month_start,
    round(sum(if(status = 'succeeded', amount, 0)), 2) as revenue,
    count(*)                                   as payments_count,
    count(*) filter (where status = 'failed')  as failed_count
from {{ ref('stg_payments') }}
group by 1
order by 1
