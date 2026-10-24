# Decisions Log

A running record of design decisions for Isaac_Agent: what was chosen, why, and what was set aside.
Newest entries go at the bottom of each section. Dates are when the decision was made.

---

## 1. Project scope

**2026-10-19 — Build a RAG chatbot first, then extend it into an agent**
- Pipeline (mentor's outline): collect a large text corpus → embed → store vectors → similarity search → filter/rerank → prompt the LLM with retrieved context → stream the answer.
- Phase 6 turns retrieval into a tool the LLM can call (agent loop).
- Why: learn each RAG stage hands-on before adding agent behaviour; the before/after comparison is the project's headline result.

**2026-10-19 — v1 covers collectible item pages only**
- Characters, bosses, trinkets, etc. are out of scope for v1.
- Why: ~700 dense, factual pages is enough to build and evaluate the full pipeline; scope can grow once retrieval works.

---

## 2. Corpus

**2026-10-19 — Corpus: English *Binding of Isaac: Rebirth* wiki on wiki.gg**
- License: CC BY-SA 4.0. Attribution goes in the app footer and README.
- Why: text-dense, actively maintained, clearly licensed, and a domain where answers can be verified by hand.
- Set aside:
  - **Course slide PDFs** (original plan): too text-sparse for good retrieval.
  - **Chinese wiki (isaac.huijiwiki.com)**: site blocked automated requests; permission unclear.
  - **Fandom Isaac wiki**: robots.txt allows the API, but Fandom's Terms of Use prohibit automated access without written permission. Also less up to date since the community moved to wiki.gg (Aug 2024).
  - **isaac-wiki-mcp repo**: covers the Lua modding API, not game content; uses keyword search, no vectors. Useful later as a reference for the agent tool design.

---

## 3. Data access

**2026-10-19 — Fetch rendered HTML pages, not the MediaWiki API**
- wiki.gg's robots.txt disallows `/api.php`, `/index.php`, and `?action=` URLs; article pages under `/wiki/` are allowed.
- Content signals: `search=yes, ai-train=no, use=reference`. This project retrieves and cites content; it does not train models.
- Parsing therefore uses BeautifulSoup on HTML instead of mwparserfromhell on wikitext.

**2026-10-19 — Polite fetching rules**
- Identify with a User-Agent; 1 request per second; cache every page and never re-fetch a cached one.
- Stop the whole run on HTTP 403 or 429. Do not retry around blocks.
- Only fetch `/wiki/...` article URLs.

**2026-10-20 — Item list comes from the `/wiki/Items` page (one request)**
- The Activated and Passive Collectibles tables give every item's link plus metadata, so per-page infobox parsing isn't needed for metadata.
- Category pages were set aside because their pagination (`?pagefrom=`) is disallowed by robots.txt.

**2026-10-21 — Item pages downloaded by a separate script (`download_page.py`)**
- Keeps re-parsing the Items table from triggering 700+ downloads.
- Resumable: cached files are skipped without sleeping. Failures (404s, timeouts) are recorded in `data/failed_pages.json` and the run continues.
- `--limit N` for testing, `--force` to re-download after wiki updates.

**2026-10-21 — Filenames: `<collectible_id>_<sanitized_name>.html`**
- Item names contain `/`, `?`, `!`, `'`, so names are sanitized to letters, digits, and underscores.
- The ID prefix keeps filenames unique and readable. `filename_for()` is the single source of truth, shared with `chunk.py`.

---

## 4. Item data model (`data/items.json`)

**2026-10-20 — Fields per item**
`name, url, entity_id, collectible_id, type (active/passive), availability, recharge, quote, description, quality, quality_raw`

**2026-10-20 — Version markers are preserved as text**
- The wiki shows DLC differences as small images whose alt text reads e.g. "(in Repentance and Repentance+)".
- `replace_version_markers()` swaps images whose alt text starts with "(" for that text; item and pickup icons are left alone.
- Why: version-specific answers depend on these markers.

**2026-10-20 — Quality: store the raw text plus the Repentance+ value**
- Some cells hold two values, e.g. "(except in Repentance+) 1 (in Repentance+) 0". `quality_raw` keeps the full text; `quality` is the last number (the Repentance+ value).
- Missing quality (legacy items) → `null`.

**2026-10-21 — Recharge time for active items**
- Read from the recharge image in the icon cell (the image *outside* the item link); e.g. "2 rooms", "Unlimited", "One time use", "4 seconds". Passive items → `null`.

**2026-10-21 — Item identity = (entity_id, name)**
- Neither field is unique alone: some distinct collectibles share a name (e.g. Broken Shovel), and IDs were reused across DLCs (Tonsil and a later item both use 5.100.474).
- Deduplication uses the pair. Result: 719 items (171 active + 548 passive).
- Set aside: dedupe by name (dropped real items), dedupe by entity_id alone (dropped Tonsil).

**2026-10-21 — Keep legacy/removed items, flagged by `availability`**
- `availability` comes from the version marker in front of the item name (no marker = "all versions").
- Example: Tonsil existed as an item only in Afterbirth and later became a trinket; its row has no quality.
- Why: players ask about older versions; the flag lets the bot say an item is legacy instead of presenting it as current.

**2026-10-21 - Chunking (`chunk.py`, Phase 1)**
- One chunk per page section (Effects, Notes, Synergies, Interactions, Trivia...); split sections over 30~1,500 characters at top-level bullet boundaries, never mid-bullet.
- Prefix every chunk with "Item — Section:".
- Preserve nested list structure and version markers.
- Skip non-text sections (In-game footage, Gallery, table of contents, navboxes).
- Add one summary chunk per item from `items.json` (name, type, availability, quality, recharge, quote, description), omitting missing fields.
- Chunk each URL only once (some items share a page, e.g. Broken Shovel).

---

## 5. Repository & environment

**2026-10-19 — Python 3.12 via uv, in a project virtual environment**
- System Python on the dev machine (Ubuntu) is 3.8, which is end-of-life and unsupported by current libraries. uv installs a separate Python without touching the system one.
- Requires Python 3.11+.

**2026-10-19 — Secrets in `.env`, template in `.env.example`**
- `.env` is gitignored; `.env.example` (variable names only) is committed so others know what to set.

**2026-10-21 — All of `data/` is gitignored**
- Raw HTML, `items.json`, chunks, and the vector store are rebuilt by the scripts.
- Why: reproducible from code, avoids large noisy diffs, and avoids redistributing CC BY-SA content in the repo.
- Rebuild order: `fetch.py` → `download_page.py` → `chunk.py`.

**2026-10-19 — Repository license: MIT (code only)**
- Wiki content remains under CC BY-SA 4.0 and is not part of the repo.

---

## 6. Models

**2026-10-19 — LLM: DeepSeek (`deepseek-flash`) via the OpenAI-compatible API**
- Suggested by mentor for low token cost; works with the `openai` Python SDK by changing `base_url`.
- Supports streaming and tool calling (needed for Phase 4 and Phase 6).
- Plan: use non-thinking mode for grounded RAG answers (faster, cheaper).
- Note: requests are processed on DeepSeek's servers; only public wiki content is sent.

**2026-10-19 — Embeddings: local model (planned: `BAAI/bge-small-en-v1.5` via sentence-transformers)**
- DeepSeek offers no embedding model, so embeddings and generation use different models.
- To be installed in Phase 2 (pulls in PyTorch).

---

## 7. Embeddings & vector store

**2026-10-22 — CPU-only PyTorch**
- Installed with `uv pip install torch --index-url https://download.pytorch.org/whl/cpu` before the other requirements.
- Why: embedding ~4,400 short chunks on CPU takes about 4 minutes, which is fine for a one-time build; avoids a multi-GB CUDA download.
- `torch` isn't listed in `requirements.txt` (it comes in as a dependency of `sentence-transformers`); the CPU install step is documented in the README setup instead.

**2026-10-22 — Embedding model: `BAAI/bge-small-en-v1.5`, run locally**
- 384-dimensional vectors, 512-token input limit (≈2,000 characters; longer input is silently truncated — the reason chunks are capped at ~1,500 characters).
- Embeddings are normalized (`normalize_embeddings=True`), so cosine similarity equals the dot product.
- Encoded in batches of 64.

**2026-10-22 — Query instruction for questions only**
- Questions are prefixed with `"Represent this sentence for searching relevant passages: "`, as recommended for BGE retrieval; chunks (passages) are embedded without it.
- Playground observation: simple questions produce right answer, but top three scores are close, gaps are bigger with query instruction

**2026-10-23 — Vector store: Chroma, persistent on disk**
- `chromadb.PersistentClient(path="data/chroma")`, which is gitignored with the rest of `data/`.
- Collection `isaac_items`, cosine distance (confirmed in the collection configuration: `'space': 'cosine'`).
- The embedding model's name is stored in the collection metadata (`embedding_model`) so search code can refuse to query with a different model.

**2026-10-23 — Full rebuild on every `index.py` run**
- The collection is deleted and recreated each run, then filled with `upsert` in batches of 1,000.
- Why: guarantees no stale chunks survive after re-chunking (upsert alone never deletes removed chunks).

**2026-10-23 — Vectors are always computed by our code; Chroma only stores and searches**
- Searches use `query_embeddings`, never `query_texts`.
- Why: the collection has Chroma's default embedding function attached. Querying with text would embed the question with a different model than the chunks, producing meaningless results without any error.

**2026-10-23 — Index result**
- 4,429 chunks stored; `collection.count()` matches `chunks.jsonl`. Embedding took ~4 minutes on CPU.
- Sanity query "What item gives me a blood laser?" → top 3: Brimstone (0.250), Technology 2 (0.286), Mega Blast (0.287), all summary chunks.
- Notes for Phase 3:
  - Distances are close together (0.25 vs 0.29), so the right answer wins only narrowly; a reranker is a likely improvement.
  - Short "which item…" questions favour summary chunks; check whether section chunks (e.g. Synergies) rank well for multi-item questions.

---

## 8. Evaluation

**2026-10-20 — 25-question evaluation set written before pipeline code (`eval/questions.jsonl`)**
- Mix: 10 fact, 5 synergy, 4 paraphrase, 3 version, 3 unanswerable.
- Answers verified against the current wiki.gg pages.
- Why: every later choice (chunk size, k, reranker, agent vs. plain RAG) needs a number to compare.

**2026-10-20 — `expected_pages` vs. `related_pages`**
- `expected_pages`: pages that actually contain the answer (used for retrieval scoring).
- `related_pages`: nice to retrieve but not required. E.g. Brimstone synergy answers live on the Brimstone page, not necessarily on the other item's page.

**2026-10-20 — Scoring rubric**
- Retrieval hit: all `expected_pages` appear in the final retrieved chunks.
- Answer score: 2 = correct and complete, 1 = partial, 0 = wrong or missing, −1 = hallucinated (confident claim not supported by the context). Hallucinations tracked separately.
