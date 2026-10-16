-- Fails if an (order_id, order_item_id) pair appears more than once.
select order_id, order_item_id, count(*) as n
from {{ ref('fct_order_items') }}
group by order_id, order_item_id
having count(*) > 1