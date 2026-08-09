# Data Quality Assessment: NorthPeak Outdoor Gear Warehouse
**Prepared for:** Data Platform & Analytics Leadership
**Data window:** 2026-03-01 – 2026-07-29 (150 days) · **Scope:** 33,556 raw orders, 4,000 customers, 30 products

---

## Headline Numbers

| Metric | Value |
|---|---|
| Orders in final warehouse (`fct_orders`) | 33,542 |
| dbt tests passed | 24 / 27 |
| Pandera statistical checks passed | 3 / 5 |
| Orders with an orphaned product reference | 21 |
| Orders with a missing customer reference | 22 |
| Orders with an implausible price/quantity | 55 |

At a glance, 24/27 dbt tests and 3/5 Pandera checks passing might look like "mostly fine." The point of this report is to show why that framing is dangerously incomplete — the failures are not spread evenly across the dataset. They are almost entirely concentrated on a single day.

---

## Finding #1 — A single-day incident, not a chronic problem

Cross-referencing every failure against its date reveals the real story: **2026-06-17 alone accounts for the overwhelming majority of every data-quality issue found.** The daily order volume/flag-rate chart makes this unmistakable — a single day spikes to a **~20% data-quality flag rate**, while every other day in the 150-day window sits near 0%.

This matters for prioritization: a chronic 1-2% background error rate calls for a process fix (retrain a team, adjust a form). A single-day spike to 20% calls for an incident investigation (what deployed, what batch job ran, what changed) — a completely different response, and one that a raw pass/fail test count alone doesn't tell you to take.

**How this was caught, by tool:**
- **dbt's `relationships` test** caught 21 orders referencing a `product_id` that doesn't exist in the catalog (hard FAIL).
- **A custom dbt singular test** (`assert_no_extreme_line_totals`) caught 52 orders with a line total outside a plausible $0.50–$5,000 range (hard FAIL) — almost certainly a pricing-multiplier bug.
- **dbt's `not_null` test on customer_id** caught 22 orders with no customer link (WARN severity, by design — see Finding #3).
- **Pandera's daily-volume z-score check** independently caught the day itself as a statistical anomaly (341 orders vs. a 222-order daily average, z=4.56) — **without knowing anything about the corruption**, purely from the volume pattern. This is a genuinely different detection mechanism from dbt's row-level tests, and it's the one that actually names the *day*, not just the rows.

---

## Finding #2 — Aggregate rate thresholds would have missed this entirely

This is the most important methodological finding in this report. Pandera's two rate-threshold checks — missing-customer rate and orphaned-product rate, each measured **across the full 150-day dataset** — both **passed** (0.07% and 0.06% respectively, both comfortably under their thresholds).

Why? Because 22 and 21 bad rows spread across 33,556 total orders is a tiny aggregate percentage. **A monitoring setup that only checks an aggregate rate against a threshold would have given this incident a clean bill of health.** It was only the **time-aware, day-by-day check** (the volume z-score) that surfaced the problem at all.

**Recommendation:** Any production data-quality monitoring needs at least one check that looks at trends over time (daily/hourly granularity), not just whole-dataset aggregates. A rate threshold alone is not sufficient to catch a short, sharp incident diluted by a large denominator.

---

## Finding #3 — Deliberate severity tuning: not every flag should block the pipeline

`not_null` on `customer_id` is configured as `severity: warn`, not a hard failure, on purpose. A background rate of guest/anonymous checkouts is a normal, expected part of this business — treating every one of them as a pipeline-blocking error would create constant false-alarm fatigue, and real teams start ignoring alerts that cry wolf. The **orphaned-product relationship test**, by contrast, is a hard `ERROR` by design — there is no legitimate business reason an order should ever reference a product that doesn't exist in the catalog.

This project also deliberately runs `dbt run` (always populate the warehouse) followed by a **separate** `dbt test` step, rather than the combined `dbt build` command. `dbt build` would have correctly *blocked* `fct_orders`, `dim_customers`, and `dim_products` from ever being created on a run with a hard test failure — which is the textbook-correct, protective behavior, but it also means the marts simply wouldn't exist to explore in a portfolio demo. The tradeoff is documented explicitly in `docs/architecture.md`, including the honest gap it introduces (bad rows can land in the warehouse before the test that flags them runs) and the real production fix (a staged load with an atomic swap).

---

## Finding #4 — The AI Data Quality Copilot gives grounded, correctly-hedged answers

The RAG-based AI copilot (Ollama `qwen2.5:0.5b`, running entirely locally) was tested against both in-scope and out-of-scope questions:

- Asked *"What happened on the incident day and what caused it?"*, it correctly cited the real 341-vs-222 order figures and synthesized an explanation from the incident summary and runbook entries — see `docs/copilot_transcript_examples.md` for the full, real transcripts (not paraphrased).
- Asked *"What is the capital of France?"* (deliberately out of scope), it correctly refused rather than hallucinating an answer, because the retrieval step's best match distance (1.88) exceeded the calibrated guardrail threshold (1.4).

**This is the practical value case for the copilot:** any team member — not just the data engineer who wrote the dbt tests — can ask "is anything wrong with the data right now, and why?" in plain English and get an answer grounded in the actual, current test results, with sources attached to verify against.

---

## Finding #5 — AI-assisted rule authoring works, but needs a human reviewer (by design)

`rag/suggest_validation_rules.py` was tested by asking the same local model to draft validation rules for `raw_payments` from its real schema and a sample of real rows. The results (`reports/ai_suggested_rules/raw_payments_suggested_rules.md`) are honestly mixed: it correctly identified the real column names and proposed plausible checks for several columns, but also proposed nonsensical numeric ranges for ID-string columns and guessed at category values (e.g., "Pending"/"Completed") that don't actually appear in the real data (the real `status` values are Captured/Failed/Refunded).

This is disclosed directly in this report rather than hidden, because it's the entire justification for keeping this feature strictly human-in-the-loop: the output is written to a **review file**, never auto-applied to the validation suite. A tiny (400MB) local model run under real hardware constraints is genuinely useful as a **first-draft accelerant** — it gets a human engineer looking at real column names and plausible starting points faster than a blank page — but is not, and should not be treated as, a substitute for a reviewer who actually knows the data.

---

## Summary Recommendation Priority

| Priority | Action | Finding Addressed |
|---|---|---|
| 1 | Investigate what deployed/ran on 2026-06-17 as a specific incident, not a general "data quality is at 89%" ticket | #1 |
| 2 | Add at least one time-aware (daily-granularity) statistical check to any production DQ monitoring, not just aggregate thresholds | #2 |
| 3 | Keep severity levels deliberately tuned (warn vs. error) rather than defaulting everything to hard-fail | #3 |
| 4 | Roll the AI copilot out as a team-wide "ask about data quality" tool, with sources always shown for verification | #4 |
| 5 | Use AI-suggested validation rules as a drafting aid only — always route through human review before adoption | #5 |

*Methodology note: this analysis runs on a synthetically generated dataset with a deliberately injected single-day incident (see `scripts/generate_data.py`). All numbers in this report were pulled from real dbt/Pandera/warehouse query output during this project's actual build and test runs — see `README.md` Section 9 for the full data and tooling methodology.*
