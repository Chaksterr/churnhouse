-- Fails if any silver contact row still has a raw phone.
select customer_id, phone_masked
from {{ ref('stg_customers_contact') }}
where phone_masked not like '***-***-%'
