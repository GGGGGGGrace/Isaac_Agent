from pathlib import Path
import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")

MODEL_NAME = "BAAI/bge-small-en-v1.5"
CHROMA_PATH = "data/chroma"
CHUNKS_PATH = Path("data/chunks/chunks.jsonl")
COLLECTION_NAME = "isaac_items"
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "  # questions only
RERANK_MODEL = "BAAI/bge-reranker-base"
RERANK_CANDIDATES = 20
RERANK_REFUSAL_THRESHOLD = 0.01   # top rerank score below this -> "not in the wiki", skip the LLM