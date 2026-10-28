-- Silver: PII masking. Gold must never see a raw email/phone.
-- email: local part -> "ab***", domain kept (useful, not personal)
-- phone: only last 4 digits survive
with ranked as (
    select *, row_number() over (partition by customer_id order by ingested_at desc) as rn
    from {{ source('bronze', 'customers_contact') }}
)

select
    customer_id,
    full_name,   -- synthetic feel: real project would hash this too
    concat(substr(split_part(email, '@', 1), 1, 2), '***@', split_part(email, '@', 2)) as email_masked,
    concat('***-***-', substr(phone, -4)) as phone_masked
from ranked
where rn = 1
