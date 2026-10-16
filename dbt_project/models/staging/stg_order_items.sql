select
    order_id,
    order_item_id::integer                 as order_item_id,
    product_id,
    seller_id,
    shipping_limit_date::timestamp         as shipping_limit_at,
    price::numeric                         as price,
    freight_value::numeric                 as freight_value
from {{ source('raw', 'order_items') }}