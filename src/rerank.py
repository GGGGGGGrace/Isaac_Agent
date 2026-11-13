"""
Phase 3, Step 2: rerank retrieved chunks with a cross-encoder.

Vector search (bi-encoder) embeds the question and each chunk separately, which is fast
but approximate. A cross-encoder reads the question and one chunk *together* and scores
how well the chunk answers it: more accurate, but too slow to run on every chunk.
So: vector search fetches ~20 candidates, the cross-encoder reorders them, we keep the best few.

First run downloads the model (~1 GB):
    HF_HUB_OFFLINE=0 python src/rerank.py

Test (from the repo root):
    python src/rerank.py
    python src/rerank.py "Is there an active item that rerolls every item pedestal in the room I'm in?"
"""

import sys
from functools import lru_cache

from config import RERANK_MODEL, RERANK_CANDIDATES  # first: keeps HF offline mode working

from sentence_transformers import CrossEncoder


@lru_cache(maxsize=1)
def get_reranker() -> CrossEncoder:
    """Load the cross-encoder once; later calls reuse the same object."""
    return CrossEncoder(RERANK_MODEL)


def rerank(question: str, hits: list[dict], top_n: int) -> list[dict]:
    """
    Score each (question, chunk text) pair with the cross-encoder, sort best first,
    and return the top_n hits. Each hit gains:
      - rerank_score: cross-encoder relevance (higher = more relevant)
      - vector_rank:  its rank from vector search, so you can see how far it moved
    The question is passed raw: the query instruction is only for the embedding model.
    """
    if not hits:
        return []

    pairs = [(question, h["text"]) for h in hits]
    scores = get_reranker().predict(pairs)

    rescored = []
    for h, score in zip(hits, scores):
        h = dict(h)                                   # copy: don't mutate the caller's list
        h["vector_rank"] = h.get("vector_rank", h["rank"])
        h["rerank_score"] = float(score)
        rescored.append(h)

    rescored.sort(key=lambda h: h["rerank_score"], reverse=True)
    for new_rank, h in enumerate(rescored, start=1):
        h["rank"] = new_rank

    return rescored[:top_n]


if __name__ == "__main__":
    # Standalone test: retrieve candidates, rerank, show how ranks moved.
    from search import retrieve

    question = sys.argv[1] if len(sys.argv) > 1 else "What does the D6 do and how long is its recharge?"
    candidates = retrieve(question, k=RERANK_CANDIDATES)
    reranked = rerank(question, candidates, top_n=RERANK_CANDIDATES)

    print(f"\nQ: {question}\n")
    print(f"{'new':>3}  {'old':>3}  {'score':>7}  chunk")
    for h in reranked:
        moved = h["vector_rank"] - h["rank"]
        arrow = f"↑{moved}" if moved > 0 else (f"↓{-moved}" if moved < 0 else "")
        print(f"{h['rank']:>3}  {h['vector_rank']:>3}  {h['rerank_score']:7.3f}  "
              f"{h['page']} — {h['section']}  {arrow}")