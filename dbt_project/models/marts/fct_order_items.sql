with items as (
    select * from {{ ref('stg_order_items') }}
),

orders as (
    select order_id, customer_id, order_status, purchased_at
    from {{ ref('stg_orders') }}
),

customers as (
    select customer_id, customer_state
    from {{ ref('stg_customers') }}
),

products as (
    select product_id, product_category_name
    from {{ ref('stg_products') }}
),

translation as (
    select product_category_name, product_category_name_english
    from {{ ref('stg_product_category_translation') }}
),

sellers as (
    select seller_id, seller_state
    from {{ ref('stg_sellers') }}
)

select
    i.order_id,
    i.order_item_id,
    i.product_id,
    i.seller_id,
    i.price,
    i.freight_value,
    i.shipping_limit_at,
    o.purchased_at,
    date_trunc('month', o.purchased_at)::date as purchase_month,
    o.order_status,
    o.order_status not in ('canceled', 'unavailable') as is_valid_order,
    -- English name when a translation exists, else the Portuguese name, else 'unknown'
    coalesce(t.product_category_name_english, p.product_category_name, 'unknown') as product_category,
    c.customer_state,
    s.seller_state
from items i
left join orders o      on i.order_id = o.order_id
left join customers c   on o.customer_id = c.customer_id
left join products p    on i.product_id = p.product_id
left join translation t on p.product_category_name = t.product_category_name
left join sellers s     on i.seller_id = s.seller_id