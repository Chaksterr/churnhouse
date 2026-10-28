-- GOLD: the product — 5 loud SQL rules, 0..8 points, + a reasons column.
-- Weights: month-to-month +2 | tenure<6m +2 | 2+ tickets in 90d +1
--          avg satisfaction <3 +1 | failed payment in 90d +2
-- Bands:   high >=5 | medium 3-4 | low 0-2
-- Validate: risk_validation must show churn% rising low -> medium -> high.

with scored as (
    select
        customer_id,
        churn,
        contract, tenure, tickets_last_90d, avg_satisfaction, failed_last_90d,

        if(contract = 'Month-to-month', 2, 0)
        + if(tenure < 6, 2, 0)
        + if(tickets_last_90d >= 2, 1, 0)
        + if(coalesce(avg_satisfaction < 3, false), 1, 0)
        + if(failed_last_90d > 0, 2, 0) as score,

        coalesce(
            array_join(
                filter(array[
                    if(contract = 'Month-to-month', 'month-to-month contract', null),
                    if(tenure < 6, 'tenure under 6 months', null),
                    if(tickets_last_90d >= 2,
                       concat(cast(tickets_last_90d as varchar), ' tickets in 90d'), null),
                    if(coalesce(avg_satisfaction < 3, false), 'avg satisfaction under 3', null),
                    if(failed_last_90d > 0,
                       concat(cast(failed_last_90d as varchar), ' failed payment(s) in 90d'), null)
                ], x -> x is not null),
            ' + '),
        'none') as reasons

    from {{ ref('customer_360') }}
)

select *,
       case when score >= 5 then 'high'
            when score >= 3 then 'medium'
            else 'low' end as band
from scored
