-- 1. Duplicate primary keys (expect 0)
SELECT 'orders' AS tbl, count(*) - count(DISTINCT order_id) AS duplicate_keys FROM raw.orders
UNION ALL SELECT 'customers', count(*) - count(DISTINCT customer_id) FROM raw.customers
UNION ALL SELECT 'products', count(*) - count(DISTINCT product_id) FROM raw.products
UNION ALL SELECT 'sellers', count(*) - count(DISTINCT seller_id) FROM raw.sellers;

-- 2. Fan-out risk: orders having several rows in each child table
SELECT 
    'order_items' AS tbl, 
    count(*) AS orders_covered,
    count(*) FILTER (WHERE n > 1) AS orders_with_many_rows
FROM (
    SELECT 
        order_id, 
        count(*) AS n 
    FROM raw.order_items 
    GROUP BY order_id
    ) t
UNION ALL
SELECT 'order_payments', count(*), count(*) FILTER (WHERE n > 1)
FROM (SELECT order_id, count(*) AS n FROM raw.order_payments GROUP BY order_id) t
UNION ALL
SELECT 'order_reviews', count(*), count(*) FILTER (WHERE n > 1)
FROM (SELECT order_id, count(*) AS n FROM raw.order_reviews GROUP BY order_id) t;

-- 3. Orders without any item, by status
SELECT o.order_status, count(*) AS orders_without_items
FROM raw.orders o
LEFT JOIN (SELECT DISTINCT order_id FROM raw.order_items) i USING (order_id)
WHERE i.order_id IS NULL
GROUP BY o.order_status
ORDER BY orders_without_items DESC;

-- 4. Missing delivery date by status (empty CSV fields were loaded as NULL)
SELECT order_status, count(*) AS orders,
       count(*) FILTER (WHERE order_delivered_customer_date IS NULL) AS no_delivery_date
FROM raw.orders
GROUP BY order_status
ORDER BY orders DESC;

-- 5. Two ways to compute total revenue: items vs payments
SELECT (SELECT round(sum(price::numeric + freight_value::numeric)) FROM raw.order_items) AS items_price_plus_freight,
       (SELECT round(sum(payment_value::numeric)) FROM raw.order_payments) AS payments_total;