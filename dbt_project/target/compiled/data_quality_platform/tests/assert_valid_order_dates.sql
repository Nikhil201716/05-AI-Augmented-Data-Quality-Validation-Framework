-- Singular test: orders should never be dated before the business's
-- data history begins, or in the future relative to when this pipeline
-- runs. No corruption of this kind was injected into the synthetic
-- data, so this test is expected to pass - included to show the suite
-- isn't cherry-picked to only contain tests that fail.

select *
from "warehouse"."main"."stg_orders"
where order_timestamp > current_timestamp
   or order_timestamp < timestamp '2025-01-01'