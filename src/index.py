import json
import chromadb
from pathlib import Path

from sentence_transformers import SentenceTransformer, util

MODEL_NAME = "BAAI/bge-small-en-v1.5"
CHUNKS_PATH = Path("data/chunks/chunks.jsonl")
CHROMA_PATH = "data/chroma"
COLLECTION_NAME = "isaac_items"
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "  # questions only

def create_fresh_collection(client: chromadb.ClientAPI):
    """delete any old collection and create new ones that uses cosine distance"""
    # delete if old collection exist
    try:
        client.delete_collection(name=COLLECTION_NAME)
        print(f"[chroma] deleted old collection '{COLLECTION_NAME}'")
    except Exception:
        pass

    info = {"embedding_model": MODEL_NAME}
    try:
        # Newer Chroma (1.x): distance metric goes in `configuration`.
        collection = client.create_collection(
            name=COLLECTION_NAME,
            configuration={"hnsw": {"space": "cosine"}},
            metadata=info,
        )
    except TypeError:
        # Older Chroma (0.4/0.5): distance metric goes in collection metadata.
        collection = client.create_collection(
            name=COLLECTION_NAME,
            metadata={**info, "hnsw:space": "cosine"},
        )
 
    # Confirm the metric actually took effect (print whatever this version exposes).
    print(f"[chroma] created '{COLLECTION_NAME}'")
    print(f"[chroma] metadata:      {collection.metadata}")
    print(f"[chroma] configuration: {getattr(collection, 'configuration', 'n/a')}")
    return collection


def insert_in_batches(client: chromadb.ClientAPI, collection, chunks: list[dict], vectors) -> None:
    """upsert ids, vectors, texts, and metadata, respecting Chroma's max batch size"""
    try:
        max_batch = client.get_max_batch_size()
    except Exception:
        max_batch = 5000
    batch = min(max_batch, 1000)

    for start in range(0, len(chunks), batch):
        part = chunks[start:start + batch]
        collection.upsert(ids = [c["chunk_id"] for c in part],
                          embeddings = vectors[start:start + batch].tolist(),
                          documents = [c["text"] for c in part],
                          metadatas = [c["metadata"] for c in part]
                          )
        print(f"[chroma] inserted {min(start + batch, len(chunks))}/{len(chunks)}")


def main() -> None:
    model = SentenceTransformer(MODEL_NAME)
    chunks = [json.loads(l) for l in CHUNKS_PATH.open(encoding="utf-8")]
    texts = [c["text"] for c in chunks]
    chunk_vecs = model.encode(texts, normalize_embeddings=True, batch_size=64, show_progress_bar=True)

    client = chromadb.PersistentClient(path="data/chroma")

    collection = create_fresh_collection(client)

    insert_in_batches(client, collection, chunks, chunk_vecs)

    print(f"\n[verify] collection.count() = {collection.count()} (expected {len(chunks)})")
    question = "What item gives me a blood laser?"
    q_vec = model.encode(QUERY_INSTRUCTION + question, normalize_embeddings=True)
    result = collection.query(query_embeddings=[q_vec.tolist()], n_results=3)  # never query_texts
    print(f"[verify] top 3 for: {question}")
    for cid, dist in zip(result["ids"][0], result["distances"][0]):
        print(f"  {dist:.3f}  {cid}")

if __name__ == "__main__":
    main()