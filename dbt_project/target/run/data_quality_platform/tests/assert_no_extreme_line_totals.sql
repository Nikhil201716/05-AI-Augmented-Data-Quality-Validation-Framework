
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  -- Singular test: fails if it returns any rows. Catches a pricing-bug
-- style anomaly (a unit-price multiplier error) that no schema test
-- (not_null/unique/relationships) is shaped to catch, because every
-- value here is technically present and technically numeric - it's
-- just wildly outside a plausible business range for this catalog
-- (products range from ~$15 to ~$290).

select *
from "warehouse"."main"."int_orders_enriched"
where line_total < 0.50 or line_total > 5000
  
  
      
    ) dbt_internal_test