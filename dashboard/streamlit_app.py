"""
streamlit_app.py
-----------------
Two-tab app for the AI-Augmented Data Quality & Validation Framework:

  Tab 1 - Data Quality Dashboard: dbt test results, Pandera statistical
          checks, the incident-day volume/flag-rate chart, and a
          filterable drill-through table over fct_orders.
  Tab 2 - AI Data Quality Copilot: a chat interface over the local
          RAG pipeline (rag/copilot.py) - ask plain-English questions
          about test results, get grounded, cited answers.

Run with:
    streamlit run dashboard/streamlit_app.py
"""

import json
import sys
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag.copilot import ask  # noqa: E402

DB_PATH = ROOT / "database" / "warehouse.duckdb"
DBT_TARGET = ROOT / "dbt_project" / "target"
REPORTS_DIR = ROOT / "reports"

st.set_page_config(page_title="AI Data Quality Platform", layout="wide", page_icon="🤖")


@st.cache_data
def load_warehouse_data():
    conn = duckdb.connect(str(DB_PATH), read_only=True)
    orders = conn.execute("SELECT * FROM main.fct_orders").fetchdf()
    conn.close()
    orders["order_date"] = pd.to_datetime(orders["order_timestamp"]).dt.date
    return orders


@st.cache_data
def load_dbt_results():
    with open(DBT_TARGET / "test_run_results.json", "r", encoding="utf-8") as f:
        run_results = json.load(f)
    with open(DBT_TARGET / "manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)
    nodes = manifest.get("nodes", {})
    rows = []
    for r in run_results["results"]:
        name = nodes.get(r["unique_id"], {}).get("name") or r["unique_id"].split(".")[-1]
        rows.append({"test_name": name, "status": r["status"].upper(), "failures": r.get("failures", 0) or 0})
    return pd.DataFrame(rows)


@st.cache_data
def load_pandera_results():
    with open(REPORTS_DIR / "pandera_validation_results.json", "r", encoding="utf-8") as f:
        return json.load(f)


orders = load_warehouse_data()
dbt_results = load_dbt_results()
pandera_results = load_pandera_results()

st.title("🤖 AI-Augmented Data Quality & Validation Platform")
st.caption("dbt (staging → intermediate → marts) + Pandera statistical validation + a local, "
           "citation-backed RAG copilot (Ollama qwen2.5:0.5b) — all reading from the same "
           "DuckDB warehouse this pipeline itself builds.")

tab_dashboard, tab_copilot = st.tabs(["📊 Data Quality Dashboard", "🤖 AI Copilot Chat"])

# ============================================================================
# TAB 1: Dashboard
# ============================================================================
with tab_dashboard:
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Orders in Warehouse", f"{len(orders):,}")
    k2.metric("dbt Tests Passed", f"{(dbt_results.status == 'PASS').sum()}/{len(dbt_results)}")
    k3.metric("Pandera Checks Passed", f"{pandera_results['passed']}/{pandera_results['total_checks']}")
    k4.metric("Orphaned-Product Orders", f"{int(orders.is_orphan_product.sum())}")
    k5.metric("Missing-Customer Orders", f"{int(orders.is_missing_customer.sum())}")

    st.divider()

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("dbt Test Results")
        status_counts = dbt_results.status.value_counts().reindex(["PASS", "WARN", "FAIL"]).fillna(0)
        fig1 = px.bar(x=status_counts.index, y=status_counts.values,
                       color=status_counts.index,
                       color_discrete_map={"PASS": "#2E6F40", "WARN": "#E1A100", "FAIL": "#C0392B"},
                       labels={"x": "", "y": "Test Count"})
        fig1.update_layout(height=350, showlegend=False)
        st.plotly_chart(fig1, use_container_width=True)
        with st.expander("Show failing / warning tests"):
            st.dataframe(dbt_results[dbt_results.status != "PASS"], use_container_width=True)

    with c2:
        st.subheader("Pandera Statistical Checks")
        pdf = pd.DataFrame(pandera_results["checks"])
        fig2 = px.bar(pdf, x="status", color="status",
                       color_discrete_map={"PASS": "#2E6F40", "FAIL": "#C0392B"},
                       labels={"status": ""})
        fig2.update_layout(height=350, showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)
        with st.expander("Show all Pandera check details"):
            st.dataframe(pdf[["check_name", "layer", "status", "detail"]], use_container_width=True)

    st.divider()

    st.subheader("Daily Order Volume & Data-Quality Flag Rate")
    daily = orders.groupby("order_date").agg(
        orders=("order_id", "count"),
        flag_rate=("is_orphan_product", lambda x: 100 * (x | orders.loc[x.index, "is_missing_customer"]
                                                            | orders.loc[x.index, "is_invalid_quantity"]).mean()),
    ).reset_index()
    fig3 = go.Figure()
    fig3.add_trace(go.Bar(x=daily.order_date, y=daily.orders, name="Order Volume", marker_color="#1F3A5F"))
    fig3.add_trace(go.Scatter(x=daily.order_date, y=daily.flag_rate, name="DQ Flag Rate %",
                                yaxis="y2", line=dict(color="#C0392B", width=2)))
    fig3.update_layout(height=420, yaxis=dict(title="Orders"),
                        yaxis2=dict(title="Flag Rate %", overlaying="y", side="right"),
                        legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig3, use_container_width=True)
    st.caption("The incident day (2026-06-17) should show up as both a volume spike AND a flag-rate spike — "
               "that combination is what separates a real technical incident from an ordinary busy day.")

    st.divider()

    st.subheader("🔍 Drill-Through: Order Detail")
    flag_filter = st.multiselect("Show only orders with these flags",
                                  ["is_orphan_product", "is_missing_customer", "is_invalid_quantity", "amount_mismatch"])
    fdf = orders.copy()
    for flag in flag_filter:
        fdf = fdf[fdf[flag] == True]  # noqa: E712
    show_cols = ["order_id", "order_date", "customer_id", "product_id", "quantity", "unit_price",
                 "line_total", "is_orphan_product", "is_missing_customer", "is_invalid_quantity", "amount_mismatch"]
    st.dataframe(fdf[show_cols].sort_values("order_date", ascending=False), use_container_width=True, height=300)
    st.download_button("Download filtered rows as CSV", fdf[show_cols].to_csv(index=False).encode("utf-8"),
                        "flagged_orders.csv", "text/csv")

# ============================================================================
# TAB 2: AI Copilot
# ============================================================================
with tab_copilot:
    st.subheader("Ask the AI Data Quality Copilot")
    st.caption("Runs 100% locally (Ollama qwen2.5:0.5b + ChromaDB). Answers are grounded in the actual "
               "dbt test results, Pandera checks, and warehouse data shown in the Dashboard tab — every "
               "answer lists the source documents it used, and it will say so if it doesn't know something "
               "rather than guessing.")

    example_questions = [
        "What happened on the incident day?",
        "Why did the extreme line totals test fail?",
        "What usually causes an orphaned product?",
        "Is the payment data trustworthy?",
        "What does the fct_orders model contain?",
    ]
    cols = st.columns(len(example_questions))
    clicked_question = None
    for col, q in zip(cols, example_questions):
        if col.button(q, use_container_width=True):
            clicked_question = q

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    user_question = st.chat_input("Ask about test results, data quality flags, or the incident...")
    question = clicked_question or user_question

    if question:
        with st.spinner("Retrieving context and generating a grounded answer locally..."):
            result = ask(question)
        st.session_state.chat_history.append((question, result))

    for q, result in reversed(st.session_state.chat_history):
        with st.chat_message("user"):
            st.write(q)
        with st.chat_message("assistant"):
            st.write(result["answer"])
            if result["sources"]:
                with st.expander(f"Sources ({len(result['sources'])})"):
                    for h in result["sources"]:
                        st.caption(f"Distance {h['distance']:.3f} · {h['text']}")
