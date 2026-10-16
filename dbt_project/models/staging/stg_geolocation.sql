select
    geolocation_zip_code_prefix,
    geolocation_lat::numeric               as geolocation_lat,
    geolocation_lng::numeric               as geolocation_lng,
    geolocation_city,
    geolocation_state
from {{ source('raw', 'geolocation') }}