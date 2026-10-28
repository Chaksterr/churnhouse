-- GOLD: does the score actually work? churn% must rise low -> medium -> high.
-- This table is the proof for the whole dashboard.

select
    band,
    count(*)                                    as customers,
    count(*) filter (where churn)               as churned,
    round(100.0 * count(*) filter (where churn) / count(*), 1) as churn_pct
from {{ ref('customer_risk') }}
group by band
order by case band when 'low' then 1 when 'medium' then 2 when 'high' then 3 end
