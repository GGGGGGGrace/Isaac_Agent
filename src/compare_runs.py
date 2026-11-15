"""
Compare two retrieval evaluation runs question by question.

Usage (from the repo root):
    python src/compare_runs.py vector_v3 reranker_v3
    python src/compare_runs.py eval/results/retrieval_vector_v3.json eval/results/retrieval_reranker_v3.json

Arguments can be labels (looked up as eval/results/retrieval_<label>.json) or file paths.
Shows, per question, evidence@3 / evidence@5 in both runs and whether B fixed or broke it,
plus the top score (rerank score if the run was reranked, otherwise vector distance).
"""

import argparse
import json
import sys
from pathlib import Path

RESULTS_DIR = Path("eval/results")
METRICS = ("evidence@3", "evidence@5")


def load_run(arg: str) -> dict:
    path = Path(arg)
    if not path.exists():
        path = RESULTS_DIR / f"retrieval_{arg}.json"
    if not path.exists():
        sys.exit(f"[error] can't find run '{arg}' (tried {arg} and {path})")
    run = json.loads(path.read_text(encoding="utf-8"))
    run["_path"] = str(path)
    return run


def top_score(record: dict) -> str:
    """Rerank score when available (higher = better), else vector distance (lower = better)."""
    if record.get("top_rerank_score") is not None:
        return f"s{record['top_rerank_score']:.3f}"
    if record.get("top_distance") is not None:
        return f"d{record['top_distance']:.3f}"
    return "-"


def mark(v) -> str:
    return "-" if v is None else ("✓" if v else "✗")


def change(a, b) -> str:
    """How a metric changed from run A to run B."""
    if a is None or b is None or a == b:
        return ""
    return "fixed" if b else "BROKE"


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two retrieval eval runs per question.")
    parser.add_argument("run_a", help="baseline run (label or path)")
    parser.add_argument("run_b", help="new run (label or path)")
    args = parser.parse_args()

    a, b = load_run(args.run_a), load_run(args.run_b)
    qa = {r["id"]: r for r in a["questions"]}
    qb = {r["id"]: r for r in b["questions"]}

    print(f"\nA: {a['_path']}  (label={a.get('label')}, rerank={a.get('rerank', False)})")
    print(f"B: {b['_path']}  (label={b.get('label')}, rerank={b.get('rerank', False)})")

    only_a, only_b = sorted(set(qa) - set(qb)), sorted(set(qb) - set(qa))
    if only_a or only_b:
        print("\n! The runs use different question sets; only shared questions are compared.")
        if only_a:
            print(f"  only in A: {only_a}")
        if only_b:
            print(f"  only in B: {only_b}")

    shared = [qid for qid in qa if qid in qb]   # keep A's order

    print(f"\n{'id':<5} {'type':<13} {'ev@3 A→B':<10} {'ev@5 A→B':<10} {'top A':<8} {'top B':<8}  change")
    print("-" * 80)
    fixed = {m: [] for m in METRICS}
    broke = {m: [] for m in METRICS}
    for qid in shared:
        ra, rb = qa[qid], qb[qid]
        notes = []
        for m in METRICS:
            c = change(ra.get(m), rb.get(m))
            if c == "fixed":
                fixed[m].append(qid)
            elif c == "BROKE":
                broke[m].append(qid)
            if c:
                notes.append(f"{m} {c}")
        e3 = f"{mark(ra.get('evidence@3'))}→{mark(rb.get('evidence@3'))}"
        e5 = f"{mark(ra.get('evidence@5'))}→{mark(rb.get('evidence@5'))}"
        print(f"{qid:<5} {ra['type']:<13} {e3:<10} {e5:<10} {top_score(ra):<8} {top_score(rb):<8}  {', '.join(notes)}")

    print("\nSUMMARY (shared questions)")
    for m in METRICS:
        scored = [q for q in shared if qa[q].get(m) is not None and qb[q].get(m) is not None]
        na = sum(1 for q in scored if qa[q][m])
        nb = sum(1 for q in scored if qb[q][m])
        print(f"  {m}: A {na}/{len(scored)} -> B {nb}/{len(scored)}   "
              f"fixed {fixed[m] or '-'}   broke {broke[m] or '-'}")
    print("\n(top score: s = rerank score, higher is better; d = vector distance, lower is better)")


if __name__ == "__main__":
    main()