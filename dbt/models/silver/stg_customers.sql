-- Silver: one clean row per customer. Dedup: newest ingested_at wins.
-- TotalCharges rule: 11 blank rows (tenure=0 new customers) = monthly * tenure -> 0.
with ranked as (
    select *, row_number() over (partition by customer_id order by ingested_at desc) as rn
    from {{ source('bronze', 'customers') }}
)

select
    customer_id,
    gender,
    senior_citizen,
    partner = 'Yes' as partner,
    dependents = 'Yes' as dependents,
    phone_service, multiple_lines, internet_service,
    online_security, online_backup, device_protection,
    tech_support, streaming_tv, streaming_movies,
    contract, paperless_billing, payment_method,
    tenure,
    monthly_charges,
    coalesce(total_charges, monthly_charges * tenure) as total_charges,  -- the 11 blanks -> 0
    churn = 'Yes' as churn
from ranked
where rn = 1
