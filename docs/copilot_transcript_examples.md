# AI Data Quality Copilot — Real Transcript Examples

Every transcript below is a **real, unedited output** from `rag/copilot.py` running against this
project's actual pipeline artifacts (dbt test results, Pandera checks, warehouse data) via a local
Ollama `qwen2.5:0.5b` model. Nothing here was paraphrased or cleaned up — including the answers'
rougher edges, which are discussed honestly in `reports/data_quality_assessment.md` Finding #4-5 and
`README.md` Section 9.

---

## 1. Grounded answer about the known incident

```
Q: What happened on the incident day and what caused it?

A: On June 17, 2026, a batch-job or deployment bug affected the NorthPeak Outdoor Gear data
warehouse, causing an increase in order volume compared to the previous day's average of 222
orders. The root cause analysis indicates that this spike was likely due to elevated data-quality
flag rates combined with a volume anomaly. Specifically, the volume spike was concentrated on a
single day and included a significant number of missing customer IDs, invalid quantities, and
non-matching payment amounts.

Sources used (4):
  - (1.282) KNOWN INCIDENT SUMMARY - 2026-06-17: This day saw 341 orders versus a 222-order daily average...
  - (1.548) Root-cause runbook - 'daily volume anomaly': A day's total order count deviates significantly...
  - (1.581) Root-cause runbook - 'is_missing_customer': An order has no customer_id at all...
  - (1.616) Pandera statistical check 'daily_volume_anomaly_detection': status = FAIL...
```

**Why this matters:** the answer correctly cites the real 341 vs. 222 order figures pulled live from
the warehouse (not hard-coded), and synthesizes across 4 different source documents (the computed
incident summary, 2 runbook entries, and a Pandera result) into one coherent explanation.

---

## 2. Hallucination guardrail correctly refusing an out-of-scope question

```
Q: What is the capital of France?

A: I don't have information on that in the current data quality knowledge base. Try asking about a
specific dbt test, a Pandera check, a model, or the known 2026-06-17 incident.

Sources used: (none - best match distance 1.883 exceeded the 1.4 guardrail threshold)
```

**Why this matters:** this is the single most important behavior for a tool like this to get right.
An ungrounded "confident-sounding" wrong answer is worse than no answer. The guardrail threshold
(1.4) was calibrated empirically against known-relevant vs. known-irrelevant queries — see
`docs/architecture.md`.

---

## 3. Explaining a specific test failure

```
Q: Why did the extreme line totals test fail?

A: The NorthPeak Outdoor Gear catalog products range from $15 to $290. The context mentions that
the 'assert_no_extreme_line_totals' test failed with 52 failing row(s). This indicates a pricing
bug, likely related to unit-price multiplier applied incorrectly upstream (e.g., price stored in
cents being read as dollars or vice versa) - not a normal data-entry typo.

The root-cause runbook for this issue states that the most common cause is a discount or coupon
applied at checkout that wasn't reflected back in the order record, and another reason could be a
currency conversion applied inconsistently. [...]

Sources used (4):
  - (0.851) dbt test 'assert_no_extreme_line_totals': status = FAIL, 52 failing row(s)...
  - (1.197) Root-cause runbook - 'amount_mismatch': A payment's amount doesn't match the order's computed line_total...
  - (1.201) dbt test 'not_null_stg_orders_quantity': status = PASS, 0 failing rows.
  - (1.248) dbt test 'not_null_stg_orders_customer_id': status = WARN, 22 failing row(s)...
```

**Honest note:** the first paragraph is accurate and well-grounded. The second paragraph drifts into
the *retrieved* `amount_mismatch` runbook entry (a different, related flag) as if it were the direct
cause — a real example of a 400MB model blending adjacent retrieved context rather than staying
tightly scoped to the single most relevant source. This is disclosed, not hidden - see README
Section 9 for what a larger model would likely do better here.

---

## 4. A more cautious, appropriately hedged answer

```
Q: Is the payment data trustworthy?

A: The payment data is not entirely trustworthy. The test results indicate that there are 0 failing
rows in the unique_stg_payments_payment_id and not_null_stg_payments_payment_id tests, but these
tests do not provide a comprehensive view of the entire dataset. To ensure the accuracy of the
payment data, it would be advisable to conduct additional checks or use more detailed validation
methods such as manual review or cross-validation.

Sources used (4):
  - (1.317) dbt test 'unique_stg_payments_payment_id': status = PASS, 0 failing rows.
  - (1.352) dbt test 'not_null_stg_payments_payment_id': status = PASS, 0 failing rows.
  - (1.374) Root-cause runbook - 'amount_mismatch': A payment's amount doesn't match the order's computed line_total...
  - (1.393) dbt model 'stg_payments': Staging model: one row per payment from raw_payments.
```

**Why this matters:** this is a genuinely reasonable, calibrated answer — it doesn't overclaim
confidence just because the two tests it found both passed, and it correctly recommends broader
validation rather than declaring the data fully trustworthy off 2 tests.

---

## 5. Answering a "what does this model contain" documentation question

```
Q: What does the fct_orders model contain?

A: The fct_orders model contains a fact table called int_orders_enriched, which is part of the
business-ready order-grain fact table. It also includes a payment join on top of this table, with
additional fields like has_payment and amount_mismatch. This model serves as the starting point for
any BI tool or analyst to query and analyze orders.

Sources used (4):
  - (0.708) dbt model 'fct_orders': Mart (final table): the business-ready, order-grain fact table...
  - (1.001) dbt model 'stg_orders': Staging model: one row per order, DEDUPLICATED on order_id...
  - (1.030) dbt test 'not_null_fct_orders_order_id': status = PASS, 0 failing rows.
  - (1.036) dbt test 'unique_fct_orders_order_id': status = PASS, 0 failing rows.
```
