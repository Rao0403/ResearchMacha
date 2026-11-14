# Architecture

ResearchMacha is a single-user, local research workspace. React presents research projects, a paper reader, comparisons, a reusable library and exports. FastAPI owns orchestration, validation and persistence. MySQL is authoritative; PDF files live on disk and Qdrant is a derived vector index.

~~~mermaid
flowchart TD
    U[Researcher] --> W[React / Vite / PDF.js]
    W --> A[FastAPI API]
    A --> D[(MySQL: workspaces, evidence, jobs, notes)]
    A --> F[Local PDF storage]
    A --> X[arXiv discovery]
    D --> J[Leased worker in the same API process]
    J --> F
    J --> O[OpenAI: generation and embeddings]
    J --> Q[(Qdrant: derived vector collections)]
    J --> D
    A --> R[Question retrieval and chat]
    R --> O
    R --> Q
    R --> D
    A --> E[Read-only Markdown / BibTeX / CSV renderer]
    E --> D
~~~

## Code boundaries

| Responsibility | Main files |
| --- | --- |
| API routes and contracts | backend/app/api/routes/, backend/app/schemas/ |
| Worker claims, leases, dispatch and recovery | backend/app/services/jobs.py |
| Paper ingestion and reuse | backend/app/services/storage.py, papers.py |
| Page extraction and reference boundary | backend/app/services/pdf.py |
| Atomic paper analysis and persisted chat turns | backend/app/services/analysis.py |
| Discovery, selection, membership and synthesis | backend/app/services/research.py |
| Saved comparison orchestration | backend/app/services/comparisons.py |
| Embedding-aware retrieval | backend/app/services/retrieval.py, vector_store.py |
| Provider interface and structured generation validation | backend/app/ai.py |
| Artifact metadata and deterministic exports | backend/app/services/provenance.py, exports.py |
| Personal notes and reading-state API | backend/app/api/routes/reader.py |
| Shared UI and single-flight polling | frontend/src/components/, hooks/useSingleFlightPolling.ts |

These are modules within one backend, not separately deployed services.

## Runtime flows

**Research discovery:** question → persisted project and trace → planning → arXiv search → deterministic ranking → candidate selection → review. Discovery and selection remain request-bound. Approval queues import jobs. Each import resolves the canonical arXiv paper, creates one project link and reuses ready analysis or queues analysis. Terminal transitions reconcile every project sharing a paper. Required failures block synthesis; Retry or Exclude resolves them. Once required evidence is ready, one synthesis generation is queued.

**Reader:** validated staged PDF → atomic file publication and queued analysis → immediate PDF viewing → extraction, chunks, embeddings and generated notes → atomic analysis-generation swap. Existing notes/chunks remain available if a replacement fails. Reader chat retrieves evidence, stores the user question and pending assistant turn, validates the answer and saves it. Chat is request-bound, not a leased job; interrupted pending turns are marked failed on worker-enabled startup and can be explicitly retried. Conversations and a versioned reading position reopen per paper; a citation's requested page takes precedence.

**Comparison:** two to ten library papers and/or uploads → saved comparison and job → wait for required analysis → retrieve and snapshot evidence → bounded generation → validate exact paper identities and each supported cell's source → save result. Editing the goal or membership preserves the old result and marks it outdated. Replacement requires an explicit action. Ready library papers are not analyzed again.

**Personal notes:** explicit create/update/delete → paper-scoped validation and optimistic version checks → MySQL. They are independent of generated summaries. Unsaved drafts are backed up in the current browser tab; saved notes survive reanalysis. Drafts are not exports or database backups.

**Export:** saved workspace → recorded artifact sources → optional selected saved personal notes → deterministic renderer → download. No retrieval, models, writes or jobs. Research/comparison exports retain the saved result's goal, source identities, warnings and date when available. Legacy gaps are labelled rather than inferred.

## Durable work and consistency

Use one API process. FastAPI lifespan starts the worker with concurrency one by default. Job rows contain an idempotency key, target IDs, requested generation, attempt count, worker identity and lease. Claims use row locks with skip-locked semantics on MySQL.

The worker renews leases between phases, recovers jobs owned by an earlier local worker at startup, and reclaims expired work up to the configured attempt limit. Shutdown stops new claims. Work can be recovered after interruption; an external model call interrupted before its database commit may need to run again and incur a new charge. This is not an exactly-once guarantee for provider billing.

Paper analysis builds a replacement before swapping chunks/summary/highlights in one SQL transaction. Comparison and synthesis writes recheck the requested generation. Synthesis refreshes the project under a lock so a stale session cannot overwrite a concurrently edited evidence set. Failed replacement synthesis retains a prior successful AI brief.

Status GETs are read-only. Frontend polling waits for the previous request to settle, aborts on identity changes and uses lightweight status endpoints. Detail and generated content are fetched on relevant transitions.

## Evidence and model boundary

The default settings are gpt-6-luna, reasoning none, and text-embedding-3-small. See [.env.example](../.env.example) for operation-specific token/time limits. The provider interface supports OpenAI and explicit offline mock mode. Startup does not make a model probe or automatically upgrade a model.

Structured schema/evidence validation permits one repair attempt; authentication, quota, incomplete-response and transport failures do not silently trigger larger models. SDK retries are disabled. Actual usage is logged. Offline tests do not measure live output quality, prices or latency.

New chunks stay within one PDF page and target 1,800 characters. A deterministic standalone References/Bibliography heading stops evidence extraction, including subsequent appendices. Layouts without a supported heading may retain reference text. Existing analyses are filtered at retrieval without automatic paid reanalysis.

Summary/chat/brief/comparison outputs select supplied evidence identifiers. The backend resolves quotations from source text and validates chunk identity, page range, excerpt membership and multi-paper identity. Comparison uses short request-local labels, eight dimensions, bounded cells and the existing 6,000-token default. Citations prove source identity and quotation validity; they do not automatically prove every interpretation is scientifically correct.

Embedding fingerprints and dimensions prevent incompatible spaces from being compared or placed in the same collection. Qdrant collections are fingerprint-namespaced. Compatible SQL vectors can provide fallback ranking; unavailable/incompatible embeddings use lexical overlap, then initial chunks with a warning. Hash embeddings are exclusive to mock mode. MySQL paper/memory rows remain authoritative.

## Saved artifacts and exports

New briefs record the question, generation, creation time, paper metadata, analysis generations and evidence IDs. Comparisons retain an evidence snapshot and original goal. Previous results keep their original provenance after edits or unsuccessful replacements.

Markdown distinguishes generated findings, source quotations and personal commentary. BibTeX uses only recorded title/authors/year/arXiv fields and marks unverified uploaded-paper metadata. CSV includes eight dimensions, citations, public sources, goal, mode, date and warnings, with spreadsheet formula protection. Local PDF links require this installation.

No automatic metadata lookup, reindexing or model call occurs during export or migrations.

## Deliberate boundaries

Keep FastAPI, React, MySQL, Qdrant and local PDFs. No authentication, ownership isolation, collaboration, OCR, external queues or hosted deployment was added. Public hosting needs authentication/ownership, rate limits, shared durable storage and a separate worker deployment. [Recovery and data](data-and-recovery.md) explains preservation and manual reanalysis.
