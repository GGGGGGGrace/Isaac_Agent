import sys
import argparse
from functools import lru_cache

import chromadb

from config import MODEL_NAME, CHROMA_PATH, COLLECTION_NAME, QUERY_INSTRUCTION
from sentence_transformers import SentenceTransformer



@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    """Load the embedding model once; later calls reuse the same object."""
    return SentenceTransformer(MODEL_NAME)


@lru_cache(maxsize=1)
def get_collection():
    """
    Open the existing Chroma collection once (never create or rebuild it here),
    and refuse to search if it was indexed with a different embedding model.
    """
    client = chromadb.PersistentClient(path=CHROMA_PATH)

    # open, don't create. Chroma raises different exception types across
    # versions when the collection is missing, so catch broadly.
    try:
        collection = client.get_collection(name=COLLECTION_NAME)
    except Exception:
        sys.exit(f"[error] collection '{COLLECTION_NAME}' not found in {CHROMA_PATH}. "
                 f"Run `python src/index.py` first.")

    # same model on both sides, or the results are meaningless.
    indexed_with = (collection.metadata or {}).get("embedding_model")
    if indexed_with != MODEL_NAME:
        sys.exit(f"[error] collection was indexed with {indexed_with!r}, "
                 f"but search is configured for {MODEL_NAME!r}. Re-run index.py.")

    return collection

def retrieve(question: str, k: int = 10) -> list[dict]:
    model = get_model()
    q_vec = model.encode(QUERY_INSTRUCTION + question, normalize_embeddings=True)
    collection = get_collection()
    result = collection.query(
        query_embeddings=[q_vec.tolist()],
        n_results=k,
        include=["documents", "metadatas", "distances"],
    )

    ids = result["ids"][0]
    docs = result["documents"][0]
    metas = result["metadatas"][0]
    dists = result["distances"][0]

    hits = []
    for rank, (cid, text, meta, dist) in enumerate(zip(ids, docs, metas, dists), start=1):
        meta = meta or {}
        hits.append({
            "rank": rank,
            "chunk_id": cid,
            "page": meta.get("page"),
            "section": meta.get("section"),
            "distance": dist,
            "similarity": round(1 - dist, 4),   # cosine: distance = 1 - similarity
            "text": text,
        })
    return hits


def main() -> None:
    parser = argparse.ArgumentParser(description="Search the Isaac item index.")
    parser.add_argument("question", help="the question to search for (quote it)")
    parser.add_argument("--k", type=int, default=10, help="number of results (default 10)")
    parser.add_argument("--show-text", action="store_true", help="also print each chunk's text")
    args = parser.parse_args()
 
    hits = retrieve(args.question, k=args.k)
 
    print(f"\nQ: {args.question}\n")
    for h in hits:
        print(f"{h['rank']:>2}. {h['distance']:.3f}  {h['page']} — {h['section']}")
        if args.show_text:
            print("    " + h["text"].replace("\n", "\n    "))
            print()
 
 
if __name__ == "__main__":
    main()