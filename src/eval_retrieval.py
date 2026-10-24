"""
measure retrieval quality on the evaluation set.

For every question in eval/questions.jsonl, run retrieve(k) and record:
  - hit@5 / hit@10: all expected_pages appear among the pages of the top 5 / top 10
  - first_rank:     position of the first expected page (None if not found)
  - top_distance:   distance of the #1 result (used later to pick an "I don't know" threshold)
Unanswerable questions (empty expected_pages) only get top_distance.

Usage (from the repo root):
    python src/eval_retrieval.py                     # saves eval/results/retrieval_baseline.json
    python src/eval_retrieval.py --label reranker    # saves eval/results/retrieval_reranker.json
"""

import argparse
import json
import statistics
from datetime import datetime
from pathlib import Path

from config import MODEL_NAME
from search import retrieve

QUESTIONS_PATH = Path("eval/questions.jsonl")
RESULTS_DIR = Path("eval/results")
K = 10


def load_questions() -> list[dict]:
    return [json.loads(line) for line in QUESTIONS_PATH.open(encoding="utf-8") if line.strip()]


def evaluate_question(q: dict, k: int) -> dict:
    """Run one question through retrieval and score it."""
    hits = retrieve(q["question"], k=k)
    pages = [h["page"] for h in hits]          # retrieved pages, in rank order
    expected = set(q["expected_pages"])

    record = {
        "id": q["id"],
        "type": q["type"],
        "question": q["question"],
        "expected_pages": q["expected_pages"],
        "retrieved": [f"{h['page']} — {h['section']}" for h in hits],
        "top_distance": round(hits[0]["distance"], 4) if hits else None,
    }

    if not expected:
        # Unanswerable: hit@k doesn't apply (an empty set is a subset of everything).
        record.update({"hit@5": None, "hit@10": None, "first_rank": None})
        return record

    record["hit@5"] = expected.issubset(pages[:5])
    record["hit@10"] = expected.issubset(pages[:10])

    first_rank = next((i for i, p in enumerate(pages, start=1) if p in expected), None)
    record["first_rank"] = first_rank
    record["first_correct_distance"] = (
        round(hits[first_rank - 1]["distance"], 4) if first_rank else None
    )
    return record


def rate(records: list[dict], key: str) -> str:
    """Format the share of records where key is True, e.g. '17/22 (77%)'."""
    if not records:
        return "n/a"
    n = sum(1 for r in records if r[key])
    return f"{n}/{len(records)} ({100 * n / len(records):.0f}%)"


def print_report(records: list[dict]) -> dict:
    answerable = [r for r in records if r["hit@10"] is not None]
    unanswerable = [r for r in records if r["hit@10"] is None]

    # Per-question table
    print(f"\n{'id':<5} {'type':<13} {'@5':<4} {'@10':<4} {'rank':<5} {'top_dist':<8}  question")
    print("-" * 95)
    for r in records:
        mark = lambda v: "-" if v is None else ("✓" if v else "✗")
        rank = "-" if r["first_rank"] is None else str(r["first_rank"])
        print(f"{r['id']:<5} {r['type']:<13} {mark(r['hit@5']):<4} {mark(r['hit@10']):<4} "
              f"{rank:<5} {r['top_distance']:<8.3f}  {r['question'][:50]}")

    # Totals
    print("\nOVERALL (answerable questions)")
    print(f"  hit@5:  {rate(answerable, 'hit@5')}")
    print(f"  hit@10: {rate(answerable, 'hit@10')}")

    # Per type
    print("\nBY TYPE (hit@5 | hit@10)")
    by_type = {}
    for t in sorted({r["type"] for r in answerable}):
        group = [r for r in answerable if r["type"] == t]
        by_type[t] = {"hit@5": rate(group, "hit@5"), "hit@10": rate(group, "hit@10")}
        print(f"  {t:<12} {by_type[t]['hit@5']:<14} | {by_type[t]['hit@10']}")

    # Distances: is there a clean gap between real and off-topic questions?
    print("\nTOP-1 DISTANCE (lower = closer match)")
    ans_d = [r["top_distance"] for r in answerable]
    una_d = [r["top_distance"] for r in unanswerable]
    distances = {}
    if ans_d:
        distances["answerable"] = {"min": min(ans_d), "max": max(ans_d), "mean": round(statistics.mean(ans_d), 4)}
        print(f"  answerable:   min {min(ans_d):.3f}  max {max(ans_d):.3f}  mean {statistics.mean(ans_d):.3f}")
    if una_d:
        distances["unanswerable"] = {"min": min(una_d), "max": max(una_d), "mean": round(statistics.mean(una_d), 4)}
        print(f"  unanswerable: min {min(una_d):.3f}  max {max(una_d):.3f}  mean {statistics.mean(una_d):.3f}")
    if ans_d and una_d:
        if max(ans_d) < min(una_d):
            print(f"  -> clean gap: a threshold between {max(ans_d):.3f} and {min(una_d):.3f} separates them")
        else:
            print("  -> ranges overlap: a distance threshold alone won't separate them cleanly")

    # Misses, for follow-up with search.py --show-text
    misses = [r for r in answerable if not r["hit@10"]]
    if misses:
        print("\nMISSES at k=10 (inspect with: python src/search.py \"<question>\" --show-text)")
        for r in misses:
            print(f"  {r['id']}: expected {r['expected_pages']}")
            print(f"        got {r['retrieved'][:3]} ...")

    return {
        "hit@5": rate(answerable, "hit@5"),
        "hit@10": rate(answerable, "hit@10"),
        "by_type": by_type,
        "top_distance": distances,
        "misses": [r["id"] for r in misses],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval on eval/questions.jsonl.")
    parser.add_argument("--label", default="baseline", help="name for this run's results file")
    parser.add_argument("--k", type=int, default=K, help=f"results per question (default {K})")
    args = parser.parse_args()

    questions = load_questions()
    print(f"[eval] {len(questions)} questions, k={args.k}, model={MODEL_NAME}")

    records = [evaluate_question(q, args.k) for q in questions]
    summary = print_report(records)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"retrieval_{args.label}.json"
    out.write_text(json.dumps({
        "label": args.label,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "model": MODEL_NAME,
        "k": args.k,
        "summary": summary,
        "questions": records,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[eval] saved {out}")


if __name__ == "__main__":
    main()