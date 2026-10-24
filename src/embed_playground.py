"""
Embedding playground: a throwaway script for building intuition before index.py.

Run from the repo root:
    python src/embed_playground.py

Edit the lists in the "PLAY HERE" section and re-run to see how the numbers change.
The model (~130 MB) downloads on the first run, then loads from cache.
"""

import json
import random
from pathlib import Path
from config import MODEL_NAME, CHROMA_PATH, COLLECTION_NAME, QUERY_INSTRUCTION

from sentence_transformers import SentenceTransformer, util


# =============================================================================
# PLAY HERE: change these and re-run
# =============================================================================

SENTENCES = [
    "Brimstone replaces your tears with a charged blood laser.",
    "Which item turns my shots into a laser I have to charge?",
    "The Jar stores extra red hearts when you are at full health.",
    "Is there something that saves my spare hearts for later?",
    "Mom's Knife lets you throw a knife instead of shooting tears.",
]

QUESTION = "What item gives me a blood laser?"

# Passages the question is compared against (with and without the query instruction).
PASSAGES = [
    "Brimstone — Effects: Isaac's tears are replaced with a charged blood laser beam.",
    "Technology — Effects: Isaac's tears are replaced with a laser.",
    "The Jar — Summary: stores up to 4 extra red hearts.",
]

# =============================================================================


def section(title: str) -> None:
    print("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)


def main() -> None:
    section("1. Load the model")
    model = SentenceTransformer(MODEL_NAME)
    print(f"model:            {MODEL_NAME}")
    print(f"max_seq_length:   {model.max_seq_length} tokens (longer input is silently cut off)")
    print(f"vector dimension: {model.get_sentence_embedding_dimension()}")
    
    # -------------------------------------------------------------------------
    section("2. What an embedding looks like")
    vecs = model.encode(SENTENCES, normalize_embeddings=True)
    print(f"shape: {vecs.shape}   <- (number of sentences, dimensions)")
    print(f"first 8 numbers of sentence 0: {vecs[0][:8].round(3)}")
    print(f"length of vector 0: {float((vecs[0] ** 2).sum() ** 0.5):.3f}   <- 1.0 because normalized")

    # -------------------------------------------------------------------------
    section("3. Similarity matrix (cosine; 1.0 = same meaning, lower = less related)")
    sims = util.cos_sim(vecs, vecs)
    labels = [f"S{i}" for i in range(len(SENTENCES))]
    for i, s in enumerate(SENTENCES):
        print(f"  {labels[i]}: {s}")
    print("\n       " + "  ".join(f"{l:>5}" for l in labels))
    for i, row in enumerate(sims):
        print(f"  {labels[i]:>4} " + "  ".join(f"{float(v):5.2f}" for v in row))
    print("\nTry: which pairs score highest even though they share few words?")

    # -------------------------------------------------------------------------
    section("4. Query instruction: with vs. without")
    passage_vecs = model.encode(PASSAGES, normalize_embeddings=True)
    plain_q = model.encode(QUESTION, normalize_embeddings=True)
    instr_q = model.encode(QUERY_INSTRUCTION + QUESTION, normalize_embeddings=True)
    print(f"question: {QUESTION}\n")
    print(f"  {'passage':<70} {'plain':>6} {'instr':>6}")
    for p, pv in zip(PASSAGES, passage_vecs):
        a = float(util.cos_sim(plain_q, pv))
        b = float(util.cos_sim(instr_q, pv))
        print(f"  {p[:68]:<70} {a:6.3f} {b:6.3f}")
    print("\nWhat matters for retrieval is the ORDER and the GAP between the right and wrong passages,")
    print("not the absolute scores. Does the instruction widen the gap?")

    # -------------------------------------------------------------------------
    section("5. Token counts (why chunks were capped at ~1,500 characters)")
    tok = model.tokenizer
    for text in [QUESTION, PASSAGES[0], "word " * 600]:
        n = len(tok(text)["input_ids"])
        flag = "  <- over the limit, would be truncated" if n > model.max_seq_length else ""
        print(f"  {len(text):5d} chars -> {n:4d} tokens{flag}")

    # -------------------------------------------------------------------------
    section("6. Mini search over a sample of your real chunks")
    if not CHUNKS_PATH.exists():
        print(f"  {CHUNKS_PATH} not found; run chunk.py first. Skipping.")
        return

    chunks = [json.loads(l) for l in CHUNKS_PATH.open(encoding="utf-8")]
    random.seed(0)
    # Sample a few hundred chunks, but make sure Brimstone's are in there so the demo has a target.
    sample = [c for c in chunks if c["metadata"].get("page") == "Brimstone"]
    sample += random.sample(chunks, 300)
    texts = [c["text"] for c in sample]

    print(f"  embedding {len(texts)} chunks (the full index in Step 2 does all {len(chunks)})...")
    chunk_vecs = model.encode(texts, normalize_embeddings=True, batch_size=64, show_progress_bar=True)
    q = model.encode(QUERY_INSTRUCTION + QUESTION, normalize_embeddings=True)

    scores = util.cos_sim(q, chunk_vecs)[0]
    top = scores.argsort(descending=True)[:5]
    print(f"\n  question: {QUESTION}\n")
    for rank, idx in enumerate(top.tolist(), start=1):
        c = sample[idx]
        first_line = c["text"].splitlines()[0]
        print(f"  {rank}. {float(scores[idx]):.3f}  {c['chunk_id']}  |  {first_line[:60]}")
    print("\nThis is exactly what Chroma will do in Step 2, just over every chunk and with an index.")


if __name__ == "__main__":
    main()