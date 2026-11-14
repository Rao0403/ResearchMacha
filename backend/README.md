# ResearchMacha backend

FastAPI backend for saved research projects, PDF ingestion/analysis, grounded chat, comparisons, personal notes and deterministic exports.

Run commands from this directory with `.\.venv\Scripts\python.exe -m ...`.
See [setup](../docs/openai-setup.md) for OpenAI configuration, credit controls, startup, and the optional development reset. The root `.env` supplies backend credentials. Live inference uses OpenAI; automated tests use offline mocks.

Run one API process. Use additive Alembic upgrades for existing work, not the destructive development reset. See [architecture](../docs/architecture.md), [recovery](../docs/data-and-recovery.md) and [testing](../docs/testing-checklist.md).

Export endpoints are read-only:

- GET /api/exports/{paper|research|comparison}/{id}/options returns available saved personal notes and warnings.
- GET /api/exports/{kind}/{id}?format=markdown|bibtex|csv downloads saved data; CSV applies to comparisons.
- Repeated note_ids query parameters select personal notes for Markdown only. Missing/out-of-scope notes are rejected.
- Content-Disposition supplies a safe download filename and is exposed through CORS.

API documentation is available at /docs while the backend runs. No export, status read or migration starts model work.

