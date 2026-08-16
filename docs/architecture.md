# ResearchMacha Architecture

## Goal

ResearchMacha is an agentic RAG research workbench. The showcase demo has three focused workflows: autonomous research-question discovery, a single-paper reader, and multi-PDF batch summarization.

## Stack

- Frontend: React, Vite, TypeScript
- Backend: FastAPI
- Database: MySQL
- ORM and migrations: SQLAlchemy, Alembic
- Agent/RAG layer: LangChain
- Local model runtime: Ollama, defaulting to `gpt-oss:20b-cloud`
- Vector DB: optional Qdrant, with MySQL JSON embedding fallback
- PDF parsing: pypdf

## Pipeline

1. Planner: LangChain turns a research question into arXiv search queries and inclusion criteria.
2. Finder: the backend searches arXiv and ranks candidates with a transparent relevance score.
3. Selector: LangChain chooses the most relevant candidate papers for user approval, with a deterministic top-3 fallback.
4. Reader: approved or uploaded PDFs are imported, parsed, chunked, embedded, indexed, summarized, and highlighted.
5. Retriever: chat and collection synthesis retrieve question-relevant chunks through the vector store, using Qdrant when enabled and MySQL cosine similarity as fallback.
6. Synthesizer: LangChain reads available paper evidence and produces a cited brief.
7. Direction generator: the same synthesis output includes gaps, suggested experiments, and future research directions.

## Data Flow

The main persistent objects are:

- `ResearchProject`: the research question, generated queries, inclusion criteria, and synthesis JSON.
- `ResearchCandidate`: arXiv candidates ranked for a project.
- `ResearchProjectPaper`: project-to-paper membership.
- `Paper`, `PaperChunk`, `PaperSummary`, `Highlight`: existing paper reading and retrieval data.

MySQL remains the source of truth. Qdrant only stores chunk vectors and payload metadata keyed by `PaperChunk.id`, so it can be rebuilt by re-analyzing papers.

The visible frontend uses:

- `/api/research-workflows` for the autonomous question-to-brief flow.
- `/api/research-workflows/{project_id}/approve` for the only required approval action.
- `/api/research-workflows/{project_id}` for polling workflow status and triggering synthesis when papers are ready.
- `/api/papers/upload`, `/api/papers/{paper_id}/summary`, `/api/papers/{paper_id}/chat`, and `/api/papers/{paper_id}/file` for the reader.
- `/api/papers/batch-upload` and `/api/papers/batch-summary` for multi-PDF summarization.

Older `/api/research-projects` routes remain as manual/debug endpoints.

## Citation Strategy

Generated findings are only considered valid when they include citations. A citation contains the paper id or title, page number, excerpt, and chunk id where available. The backend rejects synthesis results with uncited findings, gaps, experiments, or directions.

## Why LangChain

LangChain is used for the model-facing layer: prompt templates, structured outputs, Ollama/OpenAI integrations, and chain composition. The app keeps orchestration in ordinary Python services so the system remains easy to explain and debug.

## Current Limitations

- arXiv-only discovery.
- In-process background jobs.
- MySQL JSON storage remains the default embedding store; Qdrant is opt-in with `VECTOR_PROVIDER=qdrant`.
- No OCR for scanned PDFs.
- No hosted auth or multi-user workflow.
