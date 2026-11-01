# ResearchMacha Showcase

ResearchMacha is a local-first research assistant that helps a researcher move from a question to relevant papers, cited summaries, reading notes, and next research directions.

The project is intentionally scoped as a portfolio-grade MVP: it favors explainable orchestration, inspectable state, and reliable fallbacks over a vague autonomous-agent loop.

## Showcase Features

- Research workflow: enter one research question, let the backend plan/search/rank/select papers, approve the shortlist, and receive a cited research brief.
- Paper reader: upload or open a PDF, read it in a PDF.js viewer, jump from citations/highlights to pages, and ask grounded questions.
- Batch summary: upload multiple PDFs and produce a comparison table covering main ideas, hypotheses, experiments, models/datasets, results, and conclusions.

## Architecture Summary

The app uses a React/Vite frontend and a FastAPI backend. MySQL stores durable application state. Qdrant is the default semantic retrieval layer for paper chunks and memory records, with MySQL JSON cosine retrieval as fallback.

```text
User
  |
  v
React workbench
  |
  v
FastAPI service
  |
  +--> arXiv discovery
  +--> PDF import and extraction
  +--> OpenAI structured generation and embeddings
  +--> MySQL source of truth
  +--> Qdrant vector retrieval
```

## Agentic RAG Design

ResearchMacha uses an explicit tool-using workflow instead of an opaque agent. Each research run records an `AgentRun` and ordered `AgentStep` rows.

The workflow tools are:

- `plan_search`: LLM creates search queries and inclusion criteria.
- `search_arxiv`: deterministic code queries arXiv.
- `rank_candidates`: deterministic keyword/recency ranking.
- `select_candidates`: LLM selects the shortlist, using memory signals when available.
- `import_papers`: deterministic code imports approved papers.
- `analyze_papers`: deterministic code queues analysis jobs.
- `synthesize_brief`: LLM writes a cited research brief from retrieved evidence.

LLMs make decision-heavy steps. Backend code performs execution-heavy steps. This makes the system easier to debug and explain.

## Retrieval Layer

PDFs are processed through:

- page-aware text extraction with `pypdf`;
- deterministic chunking with page ranges;
- embedding generation through the configured AI provider;
- Qdrant indexing by `PaperChunk.id`;
- MySQL embedding fallback when Qdrant is unavailable.

Reader chat and collection synthesis retrieve relevant chunks and require visible page citations. If retrieval or model output is weak, the app surfaces fallback notices instead of silently pretending everything worked.

## Memory Layer

Memory is deliberately simple:

- Project memory records accepted/rejected papers and rationales.
- User preference memory infers domains, methods, datasets, recency, and keywords from approved papers.
- Paper memory stores extracted structured facts from analyzed summaries.

MySQL is the durable source of truth for memory. Qdrant is the semantic index. If Qdrant fails, the app falls back to MySQL JSON embedding search.

## Model layer

The native OpenAI SDK is used behind the application's `AIProvider` interface:

- prompt templates;
- structured JSON outputs;
- Responses API with `gpt-6-luna`, reasoning `none`;
- `text-embedding-3-small` embedding batches;
- at most one repair/retry for schema/evidence validation or rate limiting;
- actual token usage logging and explicit provider error categories.

The orchestration remains in normal Python services. That keeps the system explainable enough for a portfolio walkthrough.

## Portfolio Talking Points

- Explainable agent workflow with persisted tool traces.
- Grounded RAG over PDFs with page-level citations.
- Qdrant vector retrieval with MySQL fallback.
- Memory that affects future selection/synthesis without becoming opaque.
- Local application state and PDF storage, with cloud generation/embeddings through OpenAI.
- Production-minded reader UI with PDF.js, citation jump-to-page, retries, and CSV export.

## Known Boundaries

- Discovery is arXiv-only.
- PDFs must be born-digital; OCR is intentionally out of scope.
- A MySQL-leased worker runs inside one FastAPI process; pending work survives restarts.
- There is no multi-user auth in the MVP.
- The memory layer is useful after repeated workflows, not on a first cold run.
- Live OpenAI quality and latency require user testing; offline fixtures demonstrate contracts rather than measured model capability.
