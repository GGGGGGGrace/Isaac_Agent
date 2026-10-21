import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from bs4 import Tag

WIKI_BASE = "https://bindingofisaacrebirth.wiki.gg"
WIKI_ITEMS = "https://bindingofisaacrebirth.wiki.gg/wiki/Items"
EXPECTED_CELLS = 6
ITEMS_PATH = Path("data/items.json")

HEADERS = {"User-Agent": "IsaacRAG/0.1"}

def fetch_url(url: str) -> str:
    """
    Fetch any wiki page and return its HTML.
    """
    print(f"[wiki] GET {url}")

    resp = requests.get(url, headers=HEADERS, timeout=10)
    if resp.status_code in (403, 429):
        sys.exit(f"[wiki] Got {resp.status_code}, stopping. Do not retry aggressively.")
    resp.raise_for_status()

    return resp.text
    
def find_table(soup: BeautifulSoup, header_id: str) -> Tag:
    header = soup.find(id=header_id)
    if header is None:
        sys.exit(f"[wiki] Could not find header '{header_id}'; page layout may differ.")
            
    items_table = header.find_next("table")
    if items_table is None:
        sys.exit(f"[wiki] Could not find the table after '{header_id}'; page layout may differ.")
            
    return items_table


def replace_version_markers(tag: Tag) -> None:
    """
    Replace version-marker images (alt text like "(in Repentance and Repentance+)")
    with their alt text, so the marker survives get_text(). Icons are left alone.
    Modifies the tag in place. Reuse this in chunk.py.
    """
    for img in tag.find_all("img"):
        alt = (img.get("alt") or "").strip()
        if alt.startswith("("):
            img.replace_with(f" {alt} ")
 
 
def clean_text(tag: Tag) -> str:
    """Markers -> text, then extract text with spaces between tags and tidy whitespace."""
    replace_version_markers(tag)
    text = tag.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)                 # collapse runs of whitespace
    text = re.sub(r"\s+([.,;:!?)])", r"\1", text)    # "Heart ." -> "Heart."
    return text.strip()
 
 
def parse_recharge(icon_cell: Tag) -> str | None:
    """
    Active items' icon cell holds two images:
      - the item icon, wrapped in <a title="Gello">  -> skip (it's the item name)
      - a recharge image NOT inside a link, alt like "2 rooms", "Unlimited",
        "One time use", "4 seconds"                  -> keep its alt text
    Returns the recharge text, joined with " / " if there are several, or None.
    """
    recharges = []
    for img in icon_cell.find_all("img"):
        if img.find_parent("a") is not None:
            continue  # the item icon inside the link
        alt = (img.get("alt") or "").strip()
        if alt:
            recharges.append(alt)
    return " / ".join(recharges) if recharges else None
 
 
def parse_table(table: Tag, item_type: str) -> list[dict]:
    """
    Turn one Items-page table into a list of item records.
    item_type is "active" or "passive".
    """
    items: list[dict] = []
    rows = table.find_all("tr")
    skipped = 0
 
    for row in rows:
        cells = row.find_all("td")
 
        # Header row is made of <th>, so it has no <td> cells.
        if not cells:
            continue
 
        # 6 cells is normal; 5 means the Quality cell is missing (e.g. Tonsil).
        # Anything else is unexpected: skip, but show it so nothing is lost silently.
        if len(cells) not in (EXPECTED_CELLS, EXPECTED_CELLS - 1):
            skipped += 1
            print(f"[parse] skipped row with {len(cells)} cells: {row.get_text(' ', strip=True)[:80]}")
            continue
 
        name_cell, id_cell, icon_cell, quote_cell, desc_cell = cells[:5]
        quality_cell = cells[5] if len(cells) == EXPECTED_CELLS else None
 
        # Name + URL come from the link in the first cell (the icon cell has a duplicate link).
        link = name_cell.find("a")
        if link is None or not link.get("href"):
            skipped += 1
            print(f"[parse] skipped row without a name link: {name_cell.get_text(strip=True)}")
            continue
 
        name = link.get_text(strip=True)
        url = urljoin(WIKI_BASE, link["href"])
 
        entity_id = id_cell.get_text(strip=True)          # e.g. "5.100.118"
        last_part = entity_id.split(".")[-1]
        collectible_id = int(last_part) if last_part.isdigit() else None
 
        recharge = parse_recharge(icon_cell) if item_type == "active" else None
 
        quote = clean_text(quote_cell)
        description = clean_text(desc_cell)
 
        # Quality may hold one value ("4") or two ("(except in Repentance+) 1 (in Repentance+) 0").
        # Keep the raw text and use the last number, which is the Repentance+ value.
        # Missing quality cell -> both fields are None.
        quality_raw = clean_text(quality_cell) if quality_cell is not None else None
        digits = re.findall(r"\d", quality_raw) if quality_raw else []
        quality = int(digits[-1]) if digits else None
 
        items.append({
            "name": name,
            "url": url,
            "entity_id": entity_id,
            "collectible_id": collectible_id,
            "type": item_type,
            "recharge": recharge,
            "quote": quote,
            "description": description,
            "quality": quality,
            "quality_raw": quality_raw,
        })
 
    print(f"[parse] {item_type}: {len(rows)} rows, {len(items)} items, {skipped} skipped")
    return items

if __name__ == "__main__":
    html = fetch_url(WIKI_ITEMS)
    soup = BeautifulSoup(html, "lxml")
    a_table = find_table(soup, "Activated_Collectibles")
    p_table = find_table(soup, "Passive_Collectibles")

    items = parse_table(a_table, "active") + parse_table(p_table, "passive")

    # Guard against the same item appearing twice in one run (keep the first).
    seen, unique = set(), []
    for item in items:
        if item["name"] in seen:
            print(f"[warn] duplicate item skipped: {item['name']}")
            continue
        seen.add(item["name"])
        unique.append(item)
    items = unique

    ITEMS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ITEMS_PATH.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[done] wrote {len(items)} items to {ITEMS_PATH}")