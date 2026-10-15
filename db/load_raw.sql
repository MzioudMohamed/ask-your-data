-- Raw layer: faithful copy of the Olist CSV files, every column as text.
-- Typing and cleaning are done later in dbt (staging models).
-- Re-runnable: drops and recreates the schema each time.

DROP SCHEMA IF EXISTS raw CASCADE;
CREATE SCHEMA raw;

CREATE TABLE raw.customers (
    customer_id text, customer_unique_id text, customer_zip_code_prefix text,
    customer_city text, customer_state text);

CREATE TABLE raw.geolocation (
    geolocation_zip_code_prefix text, geolocation_lat text, geolocation_lng text,
    geolocation_city text, geolocation_state text);

CREATE TABLE raw.order_items (
    order_id text, order_item_id text, product_id text, seller_id text,
    shipping_limit_date text, price text, freight_value text);

CREATE TABLE raw.order_payments (
    order_id text, payment_sequential text, payment_type text,
    payment_installments text, payment_value text);

CREATE TABLE raw.order_reviews (
    review_id text, order_id text, review_score text, review_comment_title text,
    review_comment_message text, review_creation_date text, review_answer_timestamp text);

CREATE TABLE raw.orders (
    order_id text, customer_id text, order_status text, order_purchase_timestamp text,
    order_approved_at text, order_delivered_carrier_date text,
    order_delivered_customer_date text, order_estimated_delivery_date text);

CREATE TABLE raw.products (
    product_id text, product_category_name text, product_name_lenght text,
    product_description_lenght text, product_photos_qty text, product_weight_g text,
    product_length_cm text, product_height_cm text, product_width_cm text);

CREATE TABLE raw.sellers (
    seller_id text, seller_zip_code_prefix text, seller_city text, seller_state text);

CREATE TABLE raw.product_category_name_translation (
    product_category_name text, product_category_name_english text);

-- HEADER MATCH makes COPY fail loudly if a CSV header differs from the table columns.
COPY raw.customers FROM '/data/raw/olist_customers_dataset.csv' WITH (FORMAT csv, HEADER MATCH);
COPY raw.geolocation FROM '/data/raw/olist_geolocation_dataset.csv' WITH (FORMAT csv, HEADER MATCH);
COPY raw.order_items FROM '/data/raw/olist_order_items_dataset.csv' WITH (FORMAT csv, HEADER MATCH);
COPY raw.order_payments FROM '/data/raw/olist_order_payments_dataset.csv' WITH (FORMAT csv, HEADER MATCH);
COPY raw.order_reviews FROM '/data/raw/olist_order_reviews_dataset.csv' WITH (FORMAT csv, HEADER MATCH);
COPY raw.orders FROM '/data/raw/olist_orders_dataset.csv' WITH (FORMAT csv, HEADER MATCH);
COPY raw.products FROM '/data/raw/olist_products_dataset.csv' WITH (FORMAT csv, HEADER MATCH);
COPY raw.sellers FROM '/data/raw/olist_sellers_dataset.csv' WITH (FORMAT csv, HEADER MATCH);
-- This file starts with an invisible BOM character, so HEADER MATCH fails on it; plain HEADER just skips the header line.
COPY raw.product_category_name_translation FROM '/data/raw/product_category_name_translation.csv' WITH (FORMAT csv, HEADER true);

-- Row counts for a quick check.
SELECT 'customers' AS table_name, count(*) AS n FROM raw.customers
UNION ALL SELECT 'geolocation', count(*) FROM raw.geolocation
UNION ALL SELECT 'order_items', count(*) FROM raw.order_items
UNION ALL SELECT 'order_payments', count(*) FROM raw.order_payments
UNION ALL SELECT 'order_reviews', count(*) FROM raw.order_reviews
UNION ALL SELECT 'orders', count(*) FROM raw.orders
UNION ALL SELECT 'products', count(*) FROM raw.products
UNION ALL SELECT 'sellers', count(*) FROM raw.sellers
UNION ALL SELECT 'product_category_name_translation', count(*) FROM raw.product_category_name_translation;