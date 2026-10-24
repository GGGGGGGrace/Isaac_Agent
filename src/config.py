from pathlib import Path
import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")

MODEL_NAME = "BAAI/bge-small-en-v1.5"
CHROMA_PATH = "data/chroma"
CHUNKS_PATH = Path("data/chunks/chunks.jsonl")
COLLECTION_NAME = "isaac_items"
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "  # questions only