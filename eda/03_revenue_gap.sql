-- Where does the gap between payments and items come from?
-- The three numbers, with signs, should add up to roughly the total gap (~165k).
WITH items AS (
    SELECT order_id, sum(price::numeric + freight_value::numeric) AS items_total
    FROM raw.order_items GROUP BY order_id),
pay AS (
    SELECT order_id, sum(payment_value::numeric) AS pay_total
    FROM raw.order_payments GROUP BY order_id)
SELECT
    round(sum(pay_total) FILTER (WHERE i.order_id IS NULL)) AS payments_on_orders_without_items,
    round(sum(items_total) FILTER (WHERE p.order_id IS NULL)) AS items_on_orders_without_payments,
    round(sum(pay_total - items_total)
          FILTER (WHERE p.order_id IS NOT NULL AND i.order_id IS NOT NULL)) AS gap_on_orders_with_both
FROM pay p
FULL JOIN items i USING (order_id);