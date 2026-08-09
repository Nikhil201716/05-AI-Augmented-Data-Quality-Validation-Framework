"""
run_pipeline.py
----------------
One-command orchestrator: regenerates the entire project from a single
source of truth - synthetic raw data -> DuckDB -> dbt (run + test) ->
Pandera statistical validation -> RAG knowledge base rebuild.

Requires Ollama installed separately with the qwen2.5:0.5b model pulled
(see README) - this script does not start Ollama itself, since it's a
background service, not a one-shot job.

Usage:
    python scripts/run_pipeline.py
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
DBT_DIR = ROOT / "dbt_project"
VALIDATION_DIR = ROOT / "validation"
RAG_DIR = ROOT / "rag"

DBT_ENV = os.environ.copy()
DBT_ENV["DBT_PROFILES_DIR"] = str(DBT_DIR)

# Resolve the dbt executable relative to the CURRENT python interpreter
# (sys.executable) rather than trusting PATH - on Windows, multiple
# Python installs on PATH can shadow each other (see README Section 9),
# so "dbt" alone is not reliable across machines/terminals.
_scripts_dir = Path(sys.executable).parent / "Scripts"
DBT_EXE = str(_scripts_dir / "dbt.exe") if (_scripts_dir / "dbt.exe").exists() else "dbt"


def run(label, cmd, cwd, env=None, allow_failure=False):
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    result = subprocess.run(cmd, cwd=cwd, env=env or os.environ)
    if result.returncode != 0 and not allow_failure:
        print(f"\nPipeline FAILED at: {label}")
        sys.exit(1)


run("STEP 1/6: Generating synthetic raw data", [sys.executable, str(SCRIPTS_DIR / "generate_data.py")], SCRIPTS_DIR)
run("STEP 2/6: Loading raw data into DuckDB", [sys.executable, str(SCRIPTS_DIR / "load_raw_to_duckdb.py")], SCRIPTS_DIR)
run("STEP 3/6: Running dbt models (staging -> intermediate -> marts)",
    [DBT_EXE, "run"], DBT_DIR, DBT_ENV)
run("STEP 4/6: Running dbt tests (some FAILs/WARNs are expected - that IS the point of this project)",
    [DBT_EXE, "test"], DBT_DIR, DBT_ENV, allow_failure=True)
run("STEP 4b/6: Preserving test results for the RAG knowledge base",
    [sys.executable, "-c",
     "import shutil; shutil.copy('target/run_results.json', 'target/test_run_results.json')"],
    DBT_DIR)
run("STEP 5/6: Running Pandera statistical validation", [sys.executable, str(VALIDATION_DIR / "pandera_checks.py")],
    VALIDATION_DIR, allow_failure=True)
run("STEP 6/6: Rebuilding the AI Copilot's RAG knowledge base", [sys.executable, str(RAG_DIR / "build_knowledge_base.py")], RAG_DIR)

print(f"\n{'=' * 70}\nPipeline completed.")
print("Next steps:")
print("  1. Make sure Ollama is running with the qwen2.5:0.5b model pulled.")
print("  2. streamlit run dashboard/streamlit_app.py")
print(f"{'=' * 70}")
