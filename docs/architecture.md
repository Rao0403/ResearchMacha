# ResearchMacha Architecture

## Goal

ResearchMacha is an agentic RAG research workbench. The showcase demo has three focused workflows: autonomous research-question discovery, a single-paper reader, and multi-PDF batch summarization.

## Stack

- Frontend: React, Vite, TypeScript
- Backend: FastAPI
- Database: MySQL
- ORM and migrations: SQLAlchemy, Alembic
- Model layer: native OpenAI SDK, Responses API with strict JSON schemas
- Generation: `gpt-6-luna` with reasoning `none`; embeddings: `text-embedding-3-small`
- Vector DB: Qdrant by default, with MySQL JSON embedding fallback
- Memory: project/user/paper memory stored in MySQL and semantically indexed in Qdrant
- PDF parsing: pypdf

## Pipeline

1. Planner: OpenAI turns a research question into arXiv search queries and inclusion criteria.
2. Finder: the backend searches arXiv and ranks candidates with a transparent relevance score.
3. Memory recall: the backend retrieves relevant user/project/paper memory signals through Qdrant, with MySQL cosine fallback.
4. Selector: OpenAI chooses from the offered candidate papers for user approval, with a memory-adjusted deterministic ranking fallback.
5. Reader: approved or uploaded PDFs are imported, parsed, chunked, embedded, indexed, summarized, highlighted, and stored as paper fact memory.
6. Retriever: chat and collection synthesis retrieve question-relevant chunks through the vector store, using Qdrant first and MySQL cosine similarity as fallback.
7. Synthesizer: OpenAI reads available paper evidence and memory signals, then produces a cited brief.
8. Direction generator: the same synthesis output includes gaps, suggested experiments, and future research directions.

PDF analysis stops at a standalone References/Bibliography heading before chunking and embedding, preserving body text before that heading on the same page. Sections after references, including appendices, are excluded from evidence. Contents pages and prose mentions are not treated as bibliography headings. When no supported heading is detected, the available text is retained. This is deterministic heading detection, not a guarantee for every PDF layout.

Existing analyses retain their stored chunks and vectors. Retrieval applies the same boundary, filters eligible IDs before vector ranking, and trims a mixed body/reference chunk in a transient view. This applies to chat, research synthesis, and batch comparison without writes or paid reanalysis. Existing summaries are retained.

Batch comparison generates a bounded content-only draft: exactly the requested row count, allowed paper IDs, a 600-character takeaway, and short cells (up to 360 characters, reduced for larger batches). ID uniqueness/completeness is validated before returning the existing response format; titles and generation metadata are supplied by the backend. The generation budget remains `AI_BATCH_MAX_OUTPUT_TOKENS=6000` by default.

## Data Flow

The main persistent objects are:

- `ResearchProject`: the research question, generated queries, inclusion criteria, and synthesis JSON.
- `ResearchCandidate`: arXiv candidates ranked for a project.
- `ResearchProjectPaper`: project-to-paper membership.
- `Paper`, `PaperChunk`, `PaperSummary`, `Highlight`: existing paper reading and retrieval data.
- `ResearchMemory`: accepted/rejected project decisions, inferred user preferences, and extracted paper facts.

MySQL remains the source of truth. Qdrant stores chunk vectors keyed by `PaperChunk.id` and memory vectors keyed by `ResearchMemory.id`, so both indexes can be rebuilt from MySQL data.

The visible frontend uses:

- `/api/research-workflows` for the autonomous question-to-brief flow.
- `/api/research-workflows/{project_id}/approve` for the only required approval action.
- `/api/research-workflows/{project_id}` for read-only workflow status, recent jobs, and blockers. Terminal import/analysis transitions reconcile state and queue synthesis; GET never starts it.
- `memory_signals` on workflow responses for visible user/project memory used by future selection and synthesis.
- `/api/papers/upload`, `/api/papers/{paper_id}/status`, `/api/papers/{paper_id}/summary`, `/api/papers/{paper_id}/chat`, and `/api/papers/{paper_id}/file` for the reader. Polling uses the lightweight status endpoint.
- `/api/papers/batch-upload` and `/api/papers/batch-summary` for multi-PDF summarization.

Older `/api/research-projects` routes remain as manual/debug endpoints.

## Citation Strategy

Summary, chat, and brief generation use evidence identifiers constrained to the supplied chunks. The backend resolves identifiers to source metadata and excerpts, then validates citations against an evidence registry. Multi-paper citations include paper ID, title, page, excerpt, and chunk ID. Unsupported IDs and uncited required findings are rejected; schema compliance alone is insufficient to prove a claim is supported. Semantic fidelity still needs user review.

## Model boundary and degraded results

`app/ai.py` keeps the existing `AIProvider` boundary and explicit `MockProvider`, with a native `OpenAIProvider`. It builds strict request-specific schemas, applies per-operation output budgets, validates evidence, classifies errors, and logs actual usage. SDK retries are disabled; structured validation/rate limits permit at most one repair/retry. No automatic model escalation or paid startup probe occurs. [OpenAI setup](openai-setup.md) describes settings and credit controls.

When generation fails, source-extractive notes/chat/briefs are visibly marked with warnings. Existing successful analysis is retained on failed reanalysis. Extraction and persistence failures remain hard failures. Embedding outages use lexical retrieval; hash vectors are exclusive to explicit mock mode. Vectors carry provider/model fingerprints and dimensions, and Qdrant collections are namespaced by fingerprint.

## Durable worker

`app/services/jobs.py` runs a leased worker from FastAPI lifespan, default concurrency one. Approval/import/analysis/synthesis mutations create idempotent MySQL job rows. The worker claims rows with locks, extends leases between phases, and recovers interrupted work. Single-process startup recovery is intentional: multiple API worker processes are unsupported. A startup guard prevents pending jobs from a previous AI provider from being replayed through paid OpenAI calls.

Analysis builds a replacement generation before its atomic SQL swap. Project reconciliation blocks on failed required items; Retry and Exclude resolve blockers. Synthesis generations prevent stale jobs from overwriting newer results. SQL remains authoritative when Qdrant is unavailable.

## Current Limitations

- arXiv-only discovery.
- In-process worker; use one API process, with MySQL-backed job persistence.
- Qdrant is the default retrieval provider for chunks and memory. MySQL JSON embeddings remain the fallback when Qdrant is unavailable or disabled.
- No OCR for scanned PDFs.
- No hosted auth or multi-user workflow.
- Local application storage does not mean offline inference: generation/embedding text is sent to OpenAI. Responses use `store=false`.
- This migration has offline contract coverage; live model quality, cost, and latency await user testing.
