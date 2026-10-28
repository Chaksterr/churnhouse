-- GOLD: one row per customer — profile + money + voice + masked identity.
-- Join discipline: events (tickets, payments) are aggregated FIRST, joined SECOND.
-- Direct joins would multiply rows silently (one customer x many events).

with ticket_agg as (
    select
        customer_id,
        count(*) as tickets_total,
        count(*) filter (where created_date >= current_date - interval '90' day) as tickets_last_90d,
        avg(satisfaction_score) as avg_satisfaction
    from {{ ref('stg_tickets') }}
    group by customer_id
),

payment_agg as (
    select
        customer_id,
        count(*) as payments_total,
        round(sum(if(status = 'succeeded', amount, 0)), 2) as lifetime_paid,
        count(*) filter (where status = 'failed') as payments_failed,
        count(*) filter (where status = 'failed'
                         and payment_date >= current_date - interval '90' day) as failed_last_90d
    from {{ ref('stg_payments') }}
    group by customer_id
)

select
    c.customer_id,
    c.gender, c.senior_citizen, c.partner, c.contract,
    c.tenure, c.monthly_charges, c.total_charges, c.churn,
    coalesce(t.tickets_total, 0)      as tickets_total,
    coalesce(t.tickets_last_90d, 0)   as tickets_last_90d,
    t.avg_satisfaction,
    coalesce(p.payments_total, 0)     as payments_total,
    p.lifetime_paid,
    coalesce(p.payments_failed, 0)    as payments_failed,
    coalesce(p.failed_last_90d, 0)    as failed_last_90d,
    k.email_masked, k.phone_masked
from {{ ref('stg_customers') }} c
left join ticket_agg t on c.customer_id = t.customer_id
left join payment_agg p on c.customer_id = p.customer_id
left join {{ ref('stg_customers_contact') }} k on c.customer_id = k.customer_id
