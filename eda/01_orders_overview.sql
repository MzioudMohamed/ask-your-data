-- 1. Order status distribution
SELECT 
    order_status, 
    count(*) AS n,
    round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct
FROM raw.orders
GROUP BY order_status
ORDER BY n DESC;

-- 2. Date range of purchases
SELECT 
    min(order_purchase_timestamp::timestamp) AS first_order, -- Le ::timestamp convertit le texte du schéma raw en
    max(order_purchase_timestamp::timestamp) AS last_order   -- date au moment de la requête, puisque tout y est stocké en texte.
FROM raw.orders;

-- 3. Orders per month
SELECT 
    date_trunc('month', order_purchase_timestamp::timestamp)::date AS month,
    count(*) AS orders
FROM raw.orders
GROUP BY 1
ORDER BY 1;

-- 4. Customers by number of orders.
-- customer_id is created per order, customer_unique_id identifies the person.
SELECT 
    orders_per_customer, 
    count(*) AS customers
FROM (
    SELECT 
        c.customer_unique_id, 
        count(*) AS orders_per_customer
    FROM raw.orders o
    JOIN raw.customers c USING (customer_id)
    GROUP BY c.customer_unique_id
) t
GROUP BY orders_per_customer
ORDER BY orders_per_customer;