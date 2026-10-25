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
- The Activated and Passive Collectibles tables give every item's link plus metadata, so per-page infobox parsing isn't needed for most metadata (see section 5 for the item pool exception).
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

---

## 5. Chunking (`chunk.py`)

**2026-10-22 — One chunk per page section, plus one summary chunk per item**
- Section chunks: one per `<h2>` section (Effects, Notes, Synergies, Interactions, Trivia, Bugs, ...). Content before the first `<h2>` (infobox, intro) is not chunked as text; the summary chunk covers it.
- `<h3>` subheadings stay inside their parent section as label lines (e.g. "Overridden by Brimstone:").
- Every chunk starts with "Page — Section:" so it is self-describing and the item name is part of what gets embedded.
- Summary chunks are built from `items.json` (type, availability, quality — both values when it changed between versions — recharge, quote, description); missing fields are omitted rather than written as "None".

**2026-10-22 — Text cleaning**
- Nested lists keep their indentation ("- " lines, 2 spaces per level); tables become one line per row (cells joined with " | ").
- Version markers kept as text; math markup replaced with its plain LaTeX source.
- Removed noise: edit links, table of contents, galleries and videos (In-game footage, Gallery sections skipped), HTML comments (MediaWiki's "NewPP limit report" leaked into chunks as text), navboxes (class `nav-box`, plus a link-density fallback that skips tables/divs whose text is over 70% link text).

**2026-10-22 — Chunk size limits**
- `MAX_CHARS = 1500`, `MIN_CHARS = 30` (near-empty chunks dropped).
- Sections are packed at top-level bullet boundaries, never mid-bullet.
- Oversized blocks (a single top-level bullet with many sub-bullets) are split at second-level bullets, with the parent line repeated at the top of every piece so each piece still says what it's about. A sentence-level fallback handles single bullets that are still too long.
- Why: the embedding model reads at most 512 tokens (≈2,000 characters); longer text is silently truncated. Before the fix, 10 chunks were over the limit (max 3,791 characters); after it, 0.

**2026-10-22 — Page identity comes from the wiki URL, not the display name**
- Two different items both display as "Odd Mushroom" in the Items table (pages `Odd_Mushroom_(Thin)` and `Odd_Mushroom_(Large)`), which caused duplicate chunk IDs and ambiguous chunk text.
- `page_title(url)` decodes the URL into a unique page title ("Odd Mushroom (Thin)"); the display name is kept separately in the summary metadata.
- Each URL is chunked only once (both Broken Shovel entries share one page).
- Repeated section titles on one page are numbered in chunk IDs ("Notes", "Notes (2)") — found on the Cursed Eye page.
- A duplicate `chunk_id` check stops the run before writing, since chunk IDs become vector-store IDs.

**2026-10-22 — Metadata is vector-store friendly**
- No `None` values or lists in chunk metadata (Chroma rejects them): missing fields are dropped, and names sharing a page are joined into one string.

**2026-10-25 — Infobox data added to summary chunks**
- Found by the retrieval baseline: questions about where to find an item (f04, f08) "hit" the right page, but no retrieved chunk contained the item pool. Pools live only in the infobox, which chunking skipped, and the Items table has no pool column.
- `parse_infobox()` now extracts the item pool (with version markers and game mode) and tags; both are added to the summary chunk.
- Infobox rows are located by label text ("Item pool", "Tags"), not class names, to stay robust to markup differences.
- Lesson: page-level hit@k hid a missing-data problem. It counts any chunk from the right page, even one without the answer.

---

## 6. Repository & environment

**2026-10-19 — Python 3.12 via uv, in a project virtual environment**
- System Python on the dev machine (Ubuntu) is 3.8, which is end-of-life and unsupported by current libraries. uv installs a separate Python without touching the system one.
- Requires Python 3.11+.

**2026-10-19 — Secrets in `.env`, template in `.env.example`**
- `.env` is gitignored; `.env.example` (variable names only) is committed so others know what to set.

**2026-10-21 — All of `data/` is gitignored**
- Raw HTML, `items.json`, chunks, and the vector store are rebuilt by the scripts.
- Why: reproducible from code, avoids large noisy diffs, and avoids redistributing CC BY-SA content in the repo.
- Rebuild order: `fetch.py` → `download_page.py` → `chunk.py` → `index.py`.

**2026-10-19 — Repository license: MIT (code only)**
- Wiki content remains under CC BY-SA 4.0 and is not part of the repo.

**2026-10-23 — Shared settings in `config.py`**
- `MODEL_NAME`, `QUERY_INSTRUCTION`, `CHROMA_PATH`, `COLLECTION_NAME`, `CHUNKS_PATH` live in one module imported by `index.py`, `search.py` and the eval scripts.
- Why: a model or path changed in one file but not another would silently produce wrong results (questions and chunks embedded by different models).

**2026-10-24 — Hugging Face offline mode**
- `config.py` sets `HF_HUB_OFFLINE=1` (via `os.environ.setdefault`), so the cached model loads without a network check or the unauthenticated-request warning. No HF token needed.
- `config` must be imported before `sentence_transformers`, because `huggingface_hub` reads the variable once at import time.
- `setdefault` lets a one-off `HF_HUB_OFFLINE=0 python src/index.py` re-download the model on a fresh machine (documented in the README).

---

## 7. Models

**2026-10-19 — LLM: DeepSeek (`deepseek-flash`) via the OpenAI-compatible API**
- Suggested by mentor for low token cost; works with the `openai` Python SDK by changing `base_url`.
- Supports streaming and tool calling (needed for Phase 4 and Phase 6).
- Plan: use non-thinking mode for grounded RAG answers (faster, cheaper).
- Note: requests are processed on DeepSeek's servers; only public wiki content is sent.

**2026-10-19 — Embeddings: local model, separate from the LLM**
- DeepSeek offers no embedding model, so embeddings and generation use different models.
- Implemented in Phase 2 with `BAAI/bge-small-en-v1.5`; details in section 8.

---

## 8. Embeddings & vector store

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
- Playground observation: simple questions produce the right answer, but the top three scores are close; the gaps are bigger with the query instruction.

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

## 9. Search (`search.py`)

**2026-10-23 — `retrieve(question, k)` as the single retrieval entry point**
- The model and collection are loaded lazily and cached with `functools.lru_cache(maxsize=1)`: the first call loads them, later calls reuse them.
- The collection is opened with `get_collection` (never created or rebuilt during search); missing collection → clear "run index.py first" message.
- Safeguard: search refuses to run if the collection's stored `embedding_model` differs from `MODEL_NAME`.
- Questions are embedded with the query instruction and searched via `query_embeddings`.
- Returns rank, chunk ID, page, section, distance, similarity (1 − distance) and text; command-line mode with `--k` and `--show-text`.

---

## 10. Evaluation

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

**2026-10-24 — Evaluation code is separate from the runtime pipeline**
- Build scripts prepare data, runtime code answers questions, evaluation scripts measure the runtime. Users never run the evaluation; it is how every later change is judged.
- Each run is saved under `eval/results/retrieval_<label>.json` (committed: small, and our own findings rather than wiki content).
- `--label` only names the output file. A run labelled "reranker" before any reranker existed produced an identical copy of the baseline; it was deleted to avoid a misleading comparison.

**2026-10-25 — Evidence-based metric added (evidence@k)**
- Page-level hit@k was 100% from the start and too lenient: almost every question names its item, and any chunk from the right page counted, even Trivia without the answer.
- Each answerable question now has an `evidence` list: short phrases taken from the wiki's answer text (specific to the answer, not just the item name). Evidence@k = a chunk in the top k contains any phrase (case- and whitespace-insensitive).
- `evidence_in_corpus` checks whether a phrase exists in any chunk at all, to tell missing data or a phrase typo apart from a retrieval failure.

**2026-10-25 — Retrieval baseline (plain vector search, k = 10)**

| Metric | Score |
|---|---|
| Page hit@5 / hit@10 | 21/22 (95%) / 22/22 (100%) |
| Evidence@3 | 15/22 (68%) |
| Evidence@5 | 18/22 (82%) |
| Evidence@10 | 21/22 (95%) |

- Page hit@5 dropped from 100% to 95% (a paraphrase question) after the infobox data enlarged the summary chunks — changing chunk content changes rankings, so the eval is rerun after every change.
- Phase 4 will pass roughly the top 5 chunks to the LLM, so evidence@5 is the number that matters. Three answers are retrieved but ranked 6th–10th.
- **Phase 3 goal:** retrieve more candidates, rerank, keep 5; raise evidence@5 toward the evidence@10 ceiling (95%). A reranker can only reorder what retrieval found, so the one question missing at k = 10 needs a separate fix.

**2026-10-25 — "I don't know" handling: loose cutoff + grounded prompt, not a tight threshold**
- Top-1 distance: answerable 0.150–0.331 (mean 0.240), unanswerable 0.333–0.485 (mean 0.400).
- The ranges no longer overlap after the infobox fix, but the margin is 0.002 and based on only 3 unanswerable questions — not reliable as a threshold.
- Plan: a loose cutoff (~0.40) to skip the LLM call for clearly off-topic questions, plus a grounded prompt in Phase 4 (answer only from the retrieved context, say so when it isn't there) for cases near the boundary, such as a non-existent item name.