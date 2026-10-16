with orders as (
    select * from {{ ref('stg_orders') }}
),

customers as (
    select customer_id, customer_unique_id, customer_state, customer_city
    from {{ ref('stg_customers') }}
),

-- Items, payments and reviews are reduced to one row per order BEFORE joining,
-- otherwise orders with several payments or items would multiply the rows (fan-out).
items as (
    select
        order_id,
        count(*)            as items_count,
        sum(price)          as items_revenue,
        sum(freight_value)  as freight_total
    from {{ ref('stg_order_items') }}
    group by order_id
),

payments as (
    select
        order_id,
        sum(payment_value) as payments_total
    from {{ ref('stg_order_payments') }}
    group by order_id
),

-- Some orders have several reviews: keep the most recent one.
latest_review as (
    select distinct on (order_id)
        order_id,
        review_score
    from {{ ref('stg_order_reviews') }}
    order by order_id, review_created_at desc nulls last, review_answered_at desc nulls last, review_id
),

joined as (
    select
        o.order_id,
        o.customer_id,
        c.customer_unique_id,
        c.customer_state,
        c.customer_city,
        o.order_status,
        o.order_status not in ('canceled', 'unavailable') as is_valid_order,
        o.purchased_at,
        date_trunc('month', o.purchased_at)::date          as purchase_month,
        o.approved_at,
        o.delivered_at,
        o.estimated_delivery_at,
        coalesce(i.items_count, 0)                          as items_count,
        coalesce(i.items_revenue, 0)                        as items_revenue,
        coalesce(i.freight_total, 0)                        as freight_total,
        coalesce(p.payments_total, 0)                       as payments_total,
        r.review_score,
        (o.order_status = 'delivered' and o.delivered_at is not null) as has_delivery_data
    from orders o
    left join customers c     on o.customer_id = c.customer_id
    left join items i         on o.order_id = i.order_id
    left join payments p      on o.order_id = p.order_id
    left join latest_review r on o.order_id = r.order_id
)

select
    joined.*,
    case when has_delivery_data
         then round((extract(epoch from (delivered_at - purchased_at)) / 86400.0)::numeric, 2)
    end as delivery_days,
    case when has_delivery_data
         then round((extract(epoch from (delivered_at - estimated_delivery_at)) / 86400.0)::numeric, 2)
    end as delivery_delay_days,
    case when has_delivery_data
         then delivered_at > estimated_delivery_at
    end as is_late
from joined