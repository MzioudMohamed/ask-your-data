select
    order_id,
    payment_sequential::integer            as payment_sequential,
    payment_type,
    payment_installments::integer          as payment_installments,
    payment_value::numeric                 as payment_value
from {{ source('raw', 'order_payments') }}