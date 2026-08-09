"""
copilot.py
----------
The retrieval + generation core of the AI Data Quality Copilot.

Pipeline: question -> embed (Chroma's built-in ONNX MiniLM) -> retrieve
top-k chunks -> hallucination guardrail (refuse if nothing relevant
enough was found) -> build a grounded prompt -> generate an answer with
a local Ollama model -> return the answer WITH its sources, so a user
can verify the claim instead of just trusting it.

Model: qwen2.5:0.5b via Ollama, run entirely locally. Chosen specifically
for its small memory footprint (~400MB) - this project was built and
tested on a 6GB-RAM machine, so the model had to be small enough to
actually load and run there. See README Section 9 for the full note on
this tradeoff (a bigger model would answer more fluently, but the whole
point of a local-first copilot is that it has to run on modest hardware
someone actually owns, not just a well-resourced dev machine).
"""

from pathlib import Path

import chromadb
import ollama

ROOT = Path(__file__).resolve().parent.parent
CHROMA_PATH = ROOT / "rag" / "knowledge_base" / "chroma_store"

OLLAMA_MODEL = "qwen2.5:0.5b"
TOP_K = 4
DISTANCE_GUARDRAIL_THRESHOLD = 1.4   # calibrated empirically - see docs/architecture.md

SYSTEM_PROMPT = (
    "You are a Data Quality Copilot for the NorthPeak Outdoor Gear data warehouse. "
    "Answer the user's question using ONLY the CONTEXT provided below - do not use "
    "any outside knowledge, and do not make up numbers or test names that are not in "
    "the context. Be concise (2-4 sentences). If the context includes specific counts "
    "or percentages, cite them. If asked something the context doesn't cover, say so "
    "plainly instead of guessing."
)

_client = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        _collection = _client.get_collection("data_quality_knowledge_base")
    return _collection


def retrieve(question: str, top_k: int = TOP_K):
    collection = _get_collection()
    res = collection.query(query_texts=[question], n_results=top_k)
    hits = []
    for doc, dist, meta, doc_id in zip(
        res["documents"][0], res["distances"][0], res["metadatas"][0], res["ids"][0]
    ):
        hits.append({"id": doc_id, "text": doc, "distance": dist, "metadata": meta})
    return hits


def ask(question: str, model: str = OLLAMA_MODEL) -> dict:
    hits = retrieve(question)

    if not hits or hits[0]["distance"] > DISTANCE_GUARDRAIL_THRESHOLD:
        return {
            "answer": "I don't have information on that in the current data quality knowledge base. "
                      "Try asking about a specific dbt test, a Pandera check, a model, or the known "
                      "2026-06-17 incident.",
            "sources": [],
            "grounded": False,
        }

    context = "\n\n".join(f"[{i+1}] {h['text']}" for i, h in enumerate(hits))
    user_prompt = f"CONTEXT:\n{context}\n\nQUESTION: {question}"

    response = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        options={"temperature": 0.1, "num_predict": 220},
    )

    return {
        "answer": response["message"]["content"].strip(),
        "sources": hits,
        "grounded": True,
    }


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "What happened on the incident day?"
    print(f"Q: {q}\n")
    result = ask(q)
    print("A:", result["answer"])
    print("\nSources used:")
    for h in result["sources"]:
        print(f"  - ({h['distance']:.3f}) {h['text'][:100]}")
