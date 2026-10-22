import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

from fetch import fetch_url, ITEMS_PATH

RAW_DIR = Path("data/raw")
FAILED_PATH = Path("data/failed_pages.json")
DELAY_SECONDS = 1.0


def filename_for(item: dict) -> str:
    """
    Safe, unique filename for an item page, e.g. "118_Brimstone.html".
    The collectible ID guarantees uniqueness; the name keeps it readable.
    chunk.py should import this so both scripts agree on filenames.
    """
    safe_name = re.sub(r"[^A-Za-z0-9_]+", "_", item["name"]).strip("_")
    prefix = item["collectible_id"] if item.get("collectible_id") is not None else "noid"
    return f"{prefix}_{safe_name}.html"


def load_items() -> list[dict]:
    if not ITEMS_PATH.exists():
        sys.exit(f"[error] {ITEMS_PATH} not found. Run `python src/fetch.py` first.")
    return json.loads(ITEMS_PATH.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Download item pages into data/raw/.")
    parser.add_argument("--limit", type=int, default=None, help="only process the first N items")
    parser.add_argument("--force", action="store_true", help="re-download pages even if cached")
    args = parser.parse_args()

    items = load_items()
    if args.limit is not None:
        items = items[: args.limit]

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    total = len(items)
    saved = cached = 0
    failed: list[dict] = []

    for i, item in enumerate(items, start=1):
        path = RAW_DIR / filename_for(item)
        label = f"[{i}/{total}] {item['name']}"

        if path.exists() and not args.force:
            cached += 1
            print(f"{label} -> cached")
            continue  # no request made, so no sleep

        try:
            html = fetch_url(item["url"])
            path.write_text(html, encoding="utf-8")
            saved += 1
            print(f"{label} -> saved {path.name}")
        except requests.RequestException as e:
            # Covers 404s, timeouts, connection errors. 403/429 already exit inside fetch_url.
            failed.append({"name": item["name"], "url": item["url"], "error": str(e)})
            print(f"{label} -> FAILED ({e})")

        time.sleep(DELAY_SECONDS)  # only after a real request

    FAILED_PATH.write_text(json.dumps(failed, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[done] saved {saved}, cached {cached}, failed {len(failed)} (of {total})")
    if failed:
        print(f"[done] failures written to {FAILED_PATH}")


if __name__ == "__main__":
    main()