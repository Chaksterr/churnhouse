-- Fails if any silver contact row still looks like a raw email.
select customer_id, email_masked
from {{ ref('stg_customers_contact') }}
where email_masked not like '%***@%'
