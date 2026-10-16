-- Fails (returns rows) if a mart lost or duplicated rows, or if revenue differs between the two marts.
select 'fct_orders row count' as check_name, a.n::numeric as mart_value, b.n::numeric as expected_value
from (select count(*) as n from {{ ref('fct_orders') }}) a
cross join (select count(*) as n from {{ ref('stg_orders') }}) b
where a.n <> b.n

union all

select 'fct_order_items row count', a.n::numeric, b.n::numeric
from (select count(*) as n from {{ ref('fct_order_items') }}) a
cross join (select count(*) as n from {{ ref('stg_order_items') }}) b
where a.n <> b.n

union all

select 'revenue: fct_orders vs fct_order_items', a.v, b.v
from (select sum(items_revenue) as v from {{ ref('fct_orders') }}) a
cross join (select sum(price) as v from {{ ref('fct_order_items') }}) b
where a.v <> b.v