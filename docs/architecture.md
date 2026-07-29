# ResearchMacha Architecture

## Goal

ResearchMacha is an agentic RAG research workbench. The core demo starts with a research question and produces a cited research brief from arXiv papers.

## Stack

- Frontend: React, Vite, TypeScript
- Backend: FastAPI
- Database: MySQL
- ORM and migrations: SQLAlchemy, Alembic
- Agent/RAG layer: LangChain
- Local model runtime: Ollama, defaulting to `llama3.2:1b`
- PDF parsing: pypdf

## Pipeline

1. Planner: LangChain turns a research question into arXiv search queries and inclusion criteria.
2. Finder: the backend searches arXiv and ranks candidates with a transparent relevance score.
3. Reader: selected PDFs are imported, parsed, chunked, embedded, summarized, and highlighted.
4. Synthesizer: LangChain reads available paper evidence and produces a cited brief.
5. Direction generator: the same synthesis output includes gaps, suggested experiments, and future research directions.

## Data Flow

The main persistent objects are:

- `ResearchProject`: the research question, generated queries, inclusion criteria, and synthesis JSON.
- `ResearchCandidate`: arXiv candidates ranked for a project.
- `ResearchProjectPaper`: project-to-paper membership.
- `Paper`, `PaperChunk`, `PaperSummary`, `Highlight`: existing paper reading and retrieval data.

The frontend calls project endpoints under `/api/research-projects`. Paper inspection still uses the existing `/api/papers` endpoints.

## Citation Strategy

Generated findings are only considered valid when they include citations. A citation contains the paper id or title, page number, excerpt, and chunk id where available. The backend rejects synthesis results with uncited findings, gaps, experiments, or directions.

## Why LangChain

LangChain is used for the model-facing layer: prompt templates, structured outputs, Ollama/OpenAI integrations, and chain composition. The app keeps orchestration in ordinary Python services so the system remains easy to explain and debug.

## Current Limitations

- arXiv-only discovery.
- In-process background jobs.
- MySQL JSON storage for embeddings.
- No OCR for scanned PDFs.
- No hosted auth or multi-user workflow.

