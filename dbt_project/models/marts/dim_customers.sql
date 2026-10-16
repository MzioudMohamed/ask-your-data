-- One row per person (customer_unique_id), built from VALID orders only.
-- A person whose orders are all canceled or unavailable does not appear here.
with valid_orders as (
    select
        customer_unique_id,
        order_id,
        purchased_at,
        customer_state,
        customer_city
    from {{ ref('fct_orders') }}
    where is_valid_order
      and customer_unique_id is not null
),

ranked as (
    select
        *,
        row_number() over (partition by customer_unique_id order by purchased_at, order_id) as order_rank
    from valid_orders
),

customers as (
    select
        customer_unique_id,
        count(*)                                           as valid_orders_count,
        min(purchased_at) filter (where order_rank = 1)    as first_purchase_at,
        min(purchased_at) filter (where order_rank = 2)    as second_purchase_at,
        min(customer_state) filter (where order_rank = 1)  as customer_state,
        min(customer_city) filter (where order_rank = 1)   as customer_city
    from ranked
    group by customer_unique_id
),

-- Reference "today": the last purchase date in the data, not the real date.
data_end as (
    select max(purchased_at) as data_end_at
    from {{ ref('fct_orders') }}
)

select
    c.customer_unique_id,
    c.customer_state,
    c.customer_city,
    c.valid_orders_count,
    c.valid_orders_count >= 2                                        as is_repeat_customer,
    c.first_purchase_at,
    date_trunc('month', c.first_purchase_at)::date                   as cohort_month,
    c.second_purchase_at,
    round((extract(epoch from (c.second_purchase_at - c.first_purchase_at)) / 86400.0)::numeric, 2)
                                                                     as days_to_second_purchase,
    coalesce(c.second_purchase_at <= c.first_purchase_at + interval '90 days', false)  as repurchased_within_90d,
    coalesce(c.second_purchase_at <= c.first_purchase_at + interval '180 days', false) as repurchased_within_180d,
    c.first_purchase_at + interval '90 days'  <= d.data_end_at       as is_observable_90d,
    c.first_purchase_at + interval '180 days' <= d.data_end_at       as is_observable_180d
from customers c
cross join data_end d