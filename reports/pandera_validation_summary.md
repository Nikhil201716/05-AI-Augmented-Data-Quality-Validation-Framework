# Pandera Statistical Validation Results

**3/5 checks passed**

## plausible_value_ranges (fct_orders) - FAIL
55 value(s) fell outside plausible ranges: {'in_range(1, 20)': 25, 'in_range(1.0, 500.0)': 30}

## email_format_valid (stg_customers) - PASS
All customer emails match a valid email pattern.

## daily_volume_anomaly_detection (fct_orders (time series)) - FAIL
1 day(s) had statistically anomalous order volume vs. the 222-order average (std=26): 2026-06-17 (341 orders, z=4.56)

## missing_customer_rate_threshold (fct_orders) - PASS
Missing-customer rate 0.07% is within the 2% acceptable threshold.

## orphan_product_rate_threshold (fct_orders) - PASS
Orphaned-product rate 0.06% is within the 1% acceptable threshold.

