-- Business-rule guard: the high band MUST churn more than the low band.
-- Returns a row (test fails) when validation stops being monotonic.

select
    'high band does not churn more than low band' as problem
from (select churn_pct from {{ ref('risk_validation') }} where band = 'high') h
cross join (select churn_pct from {{ ref('risk_validation') }} where band = 'low') l
where h.churn_pct <= l.churn_pct
