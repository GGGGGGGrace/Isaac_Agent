"""
Phase 1, Steps 3-5: turn cached item pages into chunks for embedding.

Input:  data/items.json, data/raw/*.html
Output: data/chunks/chunks.jsonl  (one JSON object per line)

Rules (see DECISIONS.md, section 8):
- One chunk per page section; sections over MAX_CHARS are split at top-level
  bullet boundaries, never mid-bullet.
- Every chunk text starts with "Item — Section:".
- Nested lists keep their structure; version markers are kept as text.
- Non-text sections (videos, gallery, contents) and navboxes are skipped.
- One summary chunk per item, built from items.json (missing fields omitted).
- Each URL is chunked once, even if several items share it.

Usage (from the repo root):
    python src/chunk.py
    python src/chunk.py --only Brimstone     # debug one page, print its chunks
"""

import argparse
import json
import re
import statistics
import sys
from collections import OrderedDict
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from fetch import ITEMS_PATH, replace_version_markers
from download_page import RAW_DIR, filename_for
from config import CHUNKS_PATH

MAX_CHARS = 1500        # soft limit for a section chunk's body (excluding the prefix)
MIN_CHARS = 30          # drop near-empty chunks
SKIP_SECTIONS = {"in-game footage", "gallery", "contents", "videos"}

# Elements that never carry useful text for retrieval.
NOISE_SELECTORS = [
    ".mw-editsection",          # "[edit]" links next to headers
    ".toc", "#toc",             # table of contents
    "[class*=nav-box]",          # navigation boxes at the bottom (e.g. "Leviathan Items")
    ".gallery", "figure", ".thumb",
    "iframe", ".embedvideo",
    "style", "script",
    ".reference", "sup.reference",
]


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def tidy(text: str) -> str:
    """Collapse whitespace and remove the space get_text() leaves before punctuation."""
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([.,;:!?)])", r"\1", text)
    text = re.sub(r"\(\s+", "(", text)
    return text.strip()


def replace_math(root: Tag) -> None:
    """Replace MediaWiki math markup with its plain LaTeX source, so formulas stay readable."""
    for span in root.select(".mwe-math-element"):
        math = span.find("math")
        latex = (math.get("alttext") if math else "") or ""
        if not latex:
            img = span.find("img")
            latex = (img.get("alt") if img else "") or ""
        latex = re.sub(r"^\{\\displaystyle\s*(.*)\}$", r"\1", latex.strip())
        span.replace_with(f" {latex} ")


def inline_text(node) -> str:
    """Text of a node, ignoring any nested lists (those are rendered separately)."""
    if isinstance(node, NavigableString):
        return str(node)
    parts = []
    for child in node.children:
        if isinstance(child, Tag) and child.name in ("ul", "ol"):
            continue
        parts.append(child.get_text(" ") if isinstance(child, Tag) else str(child))
    return tidy(" ".join(parts))


def render_list(lst: Tag, depth: int = 0) -> list[str]:
    """Render <ul>/<ol> as '- ' lines, indenting nested lists by depth."""
    lines = []
    for li in lst.find_all("li", recursive=False):
        text = inline_text(li)
        if text:
            lines.append("  " * depth + "- " + text)
        for sub in li.find_all(["ul", "ol"], recursive=False):
            lines.extend(render_list(sub, depth + 1))
    return lines


def render_table(table: Tag) -> list[str]:
    """Render a table as one line per row, cells joined with ' | '."""
    lines = []
    for row in table.find_all("tr"):
        cells = [tidy(c.get_text(" ")) for c in row.find_all(["td", "th"])]
        cells = [c for c in cells if c]
        if cells:
            lines.append(" | ".join(cells))
    return lines


def render_block(el) -> list[str]:
    """Render one top-level content element into text lines."""
    if isinstance(el, NavigableString):
        text = tidy(str(el))
        return [text] if text else []
    if not isinstance(el, Tag):
        return []
    if el.name in ("ul", "ol"):
        return render_list(el)
    if el.name == "table":
        return render_table(el)
    if el.name == "dl":
        return [t for t in (tidy(x.get_text(" ")) for x in el.find_all(["dt", "dd"])) if t]
    if el.name in ("div", "section") and el.find(["ul", "ol", "table", "p"]):
        lines = []
        for child in el.children:
            lines.extend(render_block(child))
        return lines
    text = tidy(el.get_text(" "))
    return [text] if text else []


# ---------------------------------------------------------------------------
# Page -> sections
# ---------------------------------------------------------------------------

def is_navigation(el) -> bool:
    """
    Link-density check for navigation boxes: a table/div whose visible text is
    almost entirely link text (e.g. "Leviathan Items", the site-wide navbox) is
    navigation, not content. Prose like the Bugs table has far more plain text.
    """
    if not isinstance(el, Tag) or el.name not in ("table", "div"):
        return False
    total = len(tidy(el.get_text(" ")))
    if total < 40:
        return False
    linked = sum(len(tidy(a.get_text(" "))) for a in el.find_all("a"))
    return linked / total > 0.7


def heading_of(el) -> tuple[int, str] | None:
    """
    If el is a section header, return (level, title).
    Handles both <h2>Title</h2> and MediaWiki 1.43's <div class="mw-heading"><h2>Title</h2></div>.
    """
    if not isinstance(el, Tag):
        return None
    h = None
    if el.name in ("h2", "h3", "h4"):
        h = el
    elif el.name == "div" and "mw-heading" in (el.get("class") or []):
        h = el.find(["h2", "h3", "h4"])
    if h is None:
        return None
    return int(h.name[1]), tidy(h.get_text(" "))


def extract_sections(html: str) -> list[tuple[str, list[str]]]:
    """
    Return [(section_title, lines), ...] for the article body.
    Content before the first <h2> (infobox + intro) is skipped: the summary chunk covers it.
    <h3>/<h4> subsections stay inside their parent section as a 'Title:' line.
    """
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one("#mw-content-text .mw-parser-output")
    if body is None:
        return []

    for selector in NOISE_SELECTORS:
        for el in body.select(selector):
            el.decompose()
    # HTML comments (e.g. MediaWiki's "NewPP limit report") are strings to BeautifulSoup,
    # so they'd leak into the text. Remove them all.
    for comment in body.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    replace_math(body)
    replace_version_markers(body)

    sections: list[tuple[str, list[str]]] = []
    current_title, current_lines = None, []

    for el in body.children:
        head = heading_of(el)
        if head:
            level, title = head
            if level == 2:
                if current_title is not None:
                    sections.append((current_title, current_lines))
                current_title, current_lines = title, []
            elif current_title is not None:
                current_lines.append(f"{title}:")
            continue
        if current_title is None:
            continue  # still in the intro/infobox area
        if is_navigation(el):
            continue  # navbox at the bottom of the page
        current_lines.extend(render_block(el))

    if current_title is not None:
        sections.append((current_title, current_lines))

    return [(t, ls) for t, ls in sections if t.lower() not in SKIP_SECTIONS]


# ---------------------------------------------------------------------------
# Sections -> chunks
# ---------------------------------------------------------------------------

def block_len(block: list[str]) -> int:
    return len("\n".join(block))


def parent_label(parent: str) -> str:
    """Short label repeated at the top of continuation pieces, e.g. '- The Ludovico Technique:'."""
    head = parent.split(":", 1)[0]
    if ":" in parent and len(head) <= 100:
        return head + ": (continued)"
    return parent[:80].rstrip() + "… (continued)"


def split_by_sentences(block: list[str], max_chars: int) -> list[list[str]]:
    """
    Last resort for a block that can't be split at bullets (e.g. one very long bullet).
    Splits at sentence ends; continuation pieces start with a short parent label.
    Line structure inside this block is lost, which is acceptable for these rare cases.
    """
    label = parent_label(block[0])
    sentences = re.split(r"(?<=[.!?])\s+", "\n".join(block))
    pieces, current = [], ""
    for s in sentences:
        if current and len(current) + len(s) + 1 > max_chars:
            pieces.append(current)
            current = label
        current = f"{current} {s}".strip() if current else s
    if current:
        pieces.append(current)
    return [[p] for p in pieces]


def split_oversized_block(block: list[str], max_chars: int) -> list[list[str]]:
    """
    Break a block that is longer than max_chars into smaller blocks.
    1. Split at second-level bullets ("  - "); deeper lines stay with their group.
    2. Every piece starts with the parent line, so it still says what it's about.
    3. Any piece still too long (huge parent line or huge sub-group) falls back
       to sentence splitting.
    """
    if block_len(block) <= max_chars:
        return [block]

    parent, rest = block[0], block[1:]

    groups: list[list[str]] = []
    for line in rest:
        indent = len(line) - len(line.lstrip(" "))
        if indent <= 2 or not groups:
            groups.append([line])      # a second-level bullet starts a new group
        else:
            groups[-1].append(line)    # deeper bullet: stays with its group

    pieces, current = [], [parent]
    for group in groups:
        if len(current) > 1 and block_len(current) + block_len(group) + 1 > max_chars:
            pieces.append(current)
            current = [parent]
        current.extend(group)
    pieces.append(current)

    result = []
    for piece in pieces:
        if block_len(piece) > max_chars:
            result.extend(split_by_sentences(piece, max_chars))
        else:
            result.append(piece)
    return result


def split_lines(lines: list[str], max_chars: int) -> list[str]:
    """
    Group lines into blocks (a top-level line plus its indented children), break any
    block longer than max_chars at its sub-bullets (see split_oversized_block), then
    pack blocks into chunks of at most max_chars.
    """
    blocks: list[list[str]] = []
    for line in lines:
        if line.startswith(" ") and blocks:
            blocks[-1].append(line)   # nested bullet: stays with its parent
        else:
            blocks.append([line])

    # Break any block that's too big on its own before packing.
    blocks = [piece for block in blocks for piece in split_oversized_block(block, max_chars)]

    chunks, current, size = [], [], 0
    for block in blocks:
        text = "\n".join(block)
        if current and size + len(text) + 1 > max_chars:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(text)
        size += len(text) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def page_title(url: str) -> str:
    """
    Wiki page title from its URL, e.g. ".../wiki/Odd_Mushroom_(Thin)" -> "Odd Mushroom (Thin)".
    Unlike the display name in the Items table, this is unique per page.
    """
    return unquote(url.rsplit("/wiki/", 1)[-1]).replace("_", " ")


def clean_metadata(meta: dict) -> dict:
    """Vector stores like Chroma only accept str/int/float/bool values, and no None."""
    return {k: v for k, v in meta.items() if v is not None}


def summary_chunk(item: dict) -> dict:
    """One short, dense chunk per item, built from the Items table."""
    title = page_title(item["url"])
    lines = [f"{title} — Summary:"]
    kind = "Activated (active) item" if item["type"] == "active" else "Passive item"
    lines.append(f"Type: {kind}")
    lines.append(f"Availability: {item['availability']}")
    if item.get("quality_raw"):
        # Keep both values when the quality changed between versions.
        q = item["quality_raw"] if "(" in item["quality_raw"] else str(item["quality"])
        lines.append(f"Quality: {q}")
    if item.get("recharge"):
        lines.append(f"Recharge: {item['recharge']}")
    if item.get("quote"):
        lines.append(f"Pickup quote: \"{item['quote']}\"")
    if item.get("description"):
        lines.append(f"Description: {item['description']}")

    return {
        "chunk_id": f"{item['name']}::{item['entity_id']}::summary",
        "text": "\n".join(lines),
        "metadata": clean_metadata({
            "page": title,
            "name": item["name"],
            "section": "Summary",
            "url": item["url"],
            "type": item["type"],
            "availability": item["availability"],
            "quality": item.get("quality"),
            "entity_id": item["entity_id"],
            "kind": "summary",
        }),
    }


def page_chunks(items_on_page: list[dict], html: str) -> list[dict]:
    """Section chunks for one wiki page (shared by every item that links to it)."""
    first = items_on_page[0]
    page = page_title(first["url"])   # unique per page, unlike display names
    names = "; ".join(dict.fromkeys(i["name"] for i in items_on_page))
    types = "/".join(dict.fromkeys(i["type"] for i in items_on_page))

    chunks = []
    title_counts: dict[str, int] = {}
    for title, lines in extract_sections(html):
        # Some pages repeat a section title (e.g. two "Notes" headers).
        # Number repeats so chunk IDs stay unique: "Notes", "Notes (2)", ...
        title_counts[title] = title_counts.get(title, 0) + 1
        section_key = title if title_counts[title] == 1 else f"{title} ({title_counts[title]})"

        for n, body in enumerate(split_lines(lines, MAX_CHARS), start=1):
            if len(body) < MIN_CHARS:
                continue
            chunks.append({
                "chunk_id": f"{page}::{section_key}::{n}",
                "text": f"{page} — {title}:\n{body}",
                "metadata": clean_metadata({
                    "page": page,
                    "names": names,
                    "section": title,
                    "url": first["url"],
                    "type": types,
                    "availability": first["availability"],
                    "quality": first.get("quality"),
                    "kind": "section",
                }),
            })
    return chunks


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Chunk cached item pages.")
    parser.add_argument("--only", help="process only this item name and print its chunks")
    args = parser.parse_args()

    if not ITEMS_PATH.exists():
        sys.exit(f"[error] {ITEMS_PATH} not found. Run fetch.py and download_page.py first.")
    items = json.loads(ITEMS_PATH.read_text(encoding="utf-8"))
    if args.only:
        items = [i for i in items if i["name"].lower() == args.only.lower()]
        if not items:
            sys.exit(f"[error] no item named {args.only!r} in {ITEMS_PATH}")

    # Group items by URL so each page is chunked once (e.g. both Broken Shovel entries).
    by_url: "OrderedDict[str, list[dict]]" = OrderedDict()
    for item in items:
        by_url.setdefault(item["url"], []).append(item)

    chunks: list[dict] = [summary_chunk(i) for i in items]
    missing = []

    for url, group in by_url.items():
        path = RAW_DIR / filename_for(group[0])
        if not path.exists():
            missing.append(group[0]["name"])
            continue
        chunks.extend(page_chunks(group, path.read_text(encoding="utf-8")))

    if args.only:
        for c in chunks:
            print(f"\n=== {c['chunk_id']} ({len(c['text'])} chars) ===\n{c['text']}")
        return

    # Guard against duplicate chunk IDs (they become vector store IDs in Phase 2).
    seen = set()
    for c in chunks:
        if c["chunk_id"] in seen:
            sys.exit(f"[error] duplicate chunk_id: {c['chunk_id']}")
        seen.add(c["chunk_id"])

    CHUNKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CHUNKS_PATH.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    lengths = [len(c["text"]) for c in chunks]
    sections = [c for c in chunks if c["metadata"]["kind"] == "section"]
    oversized = [c for c in sections if len(c["text"]) > MAX_CHARS + 200]
    print(f"[done] {len(by_url)} pages, {len(items)} items")
    print(f"[done] {len(chunks)} chunks ({len(chunks) - len(sections)} summary, {len(sections)} section)")
    print(f"[done] length: avg {statistics.mean(lengths):.0f}, median {statistics.median(lengths):.0f}, max {max(lengths)}")
    print(f"[done] {len(oversized)} section chunks over the soft limit (single long bullets)")
    if missing:
        print(f"[warn] {len(missing)} pages missing from {RAW_DIR}: {missing[:5]}")
    print(f"[done] wrote {CHUNKS_PATH}")


if __name__ == "__main__":
    main()