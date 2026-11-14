# ResearchMacha

![React](https://img.shields.io/badge/frontend-React%20%2B%20Vite-a44f2a)
![FastAPI](https://img.shields.io/badge/backend-FastAPI%20%2B%20SQLAlchemy-24160c)
![OpenAI](https://img.shields.io/badge/AI-OpenAI%20API-2f7a55)
![Qdrant](https://img.shields.io/badge/vector%20store-Qdrant%20default-5e8c7b)
![MySQL](https://img.shields.io/badge/database-MySQL-9c6b1f)

ResearchMacha is a local research workspace for discovering papers, reading and questioning their evidence, comparing studies, preserving personal notes and exporting useful research artifacts.

Models handle planning, selection and synthesis. Normal backend code handles ingestion, durable orchestration, validation, persistence and exports. Saved work can be reopened without generating it again.

[Architecture and runtime flows](docs/architecture.md)

## Core Workflows

- `Research`: type one research question, let the backend plan/search/select papers, approve the selected papers, then receive a cited research brief with findings, gaps, experiments, and research directions. Reopen saved questions from `Projects`; naming a project or saving a selection does not start processing.
- `Reader`: upload or open one PDF, read it in a PDF.js viewer beside structured notes, cited highlights, and grounded chat. Conversations and reading position are saved per paper; an explicit citation page takes precedence when opening a source link. `My Notes` keeps your own page-linked annotations separately, with explicit saves and browser-tab draft recovery.
- `Compare`: upload two to ten PDFs and get a saved comparison covering main idea, problem/hypothesis, experiments, models/datasets, results, and conclusions. The backend worker finishes processing after the tab closes. Reopening or saving edited details does not generate again; use `Update comparison` explicitly to replace a result.
- `Export`: download saved reading notes, research briefs or comparisons as Markdown, choose saved personal notes to include, export recorded references as BibTeX, or download comparison CSV with citations and warnings. Exports make no model calls.

Saved projects use `/projects/{project_id}` and comparisons use `/comparisons/{comparison_id}`. These URLs reopen the local workspace's stored data; they are not public sharing links. Run the additive Alembic upgrade below when updating an existing checkout. Older comparison tables that existed only in browser state cannot be recovered.

Research and comparison can reuse ready/degraded library papers without uploading or analyzing them again. Comparisons can mix library papers with uploads. Adding library papers to a saved workspace preserves its previous result; generation remains an explicit action. New comparisons include cell citations, limitations and evaluation conditions. Older saved comparisons have no retroactively invented citations; update them explicitly when needed. Reusing an analysis still incurs generation/query-embedding usage when you request a new brief or comparison.

![Reader with personal notes and export controls](docs/assets/reader.png)

Screenshot: an offline UI fixture, not real research findings. [More screenshots and walkthrough](docs/walkthrough.md).

## Stack

- Frontend: React, Vite, TypeScript, React Router, PDF.js
- Backend: FastAPI, SQLAlchemy, Alembic, MySQL
- Model layer: native OpenAI SDK, Responses API, strict structured outputs
- AI providers: `openai` (default) and `mock` (offline fixtures)
- Generation: `gpt-6-luna`, reasoning `none`; embeddings: `text-embedding-3-small`
- Vector retrieval: Qdrant by default with MySQL JSON cosine similarity as fallback
- Memory: MySQL source-of-truth rows indexed into Qdrant for semantic recall, with MySQL fallback

## Repository Layout

```text
.
|-- backend
|   |-- alembic
|   |-- app
|   |-- scripts
|   `-- tests
|-- docs
|   |-- assets
|   |-- architecture.md
|   |-- demo.md
|   |-- showcase.md
|   |-- testing-checklist.md
|   `-- walkthrough.md
`-- frontend
    `-- src
```

## Quickstart

### 1. Configure Environment

Copy `.env.example` to the repository-root `.env` if it does not already exist. Set your MySQL credentials and backend-only `OPENAI_API_KEY`. If `DATABASE_URL` is set, it takes precedence over the separate MySQL settings. Never put the key in a `VITE_` variable or commit `.env`.

Recommended local settings:

```env
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your-password
MYSQL_DATABASE=research_macha

AI_PROVIDER=openai
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=gpt-6-luna
OPENAI_EMBED_MODEL=text-embedding-3-small
OPENAI_REASONING_EFFORT=none

VECTOR_PROVIDER=qdrant
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=research_macha_chunks
QDRANT_MEMORY_COLLECTION=research_macha_memories
```

Create the database:

```sql
CREATE DATABASE IF NOT EXISTS research_macha CHARACTER SET utf8mb4;
```

Use Python 3.12+, Node.js 22+ and MySQL. Docker runs the default Qdrant service; alternatively set VECTOR_PROVIDER=mysql to use SQL vectors without Docker. OpenAI generation requires an API key and credit. [OpenAI setup](docs/openai-setup.md) covers provider settings and credit controls. Ollama is not required.

### 2. Start Qdrant

```powershell
docker compose up -d qdrant
```

### 3. Start Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -B -m alembic upgrade head
# Existing installations: skip environment/dependency creation; upgrade the schema and restart.
# Do not use a development reset to upgrade valuable work.
.\.venv\Scripts\python.exe -B -m uvicorn app.main:app --reload --port 8000
```

### 4. Start Frontend in a Second Terminal

```powershell
cd frontend
cmd /c npm ci
cmd /c npm run dev
```

Open:

```text
http://localhost:5173
```

Use one backend process. Starting it may resume previously approved jobs. [Data and recovery](docs/data-and-recovery.md) explains leases, retry, backups and opt-in legacy reanalysis.

## Testing

Run checks:

```powershell
cd backend
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider

cd ..\frontend
cmd /c npm test -- --run
cmd /c npm exec tsc -- -p tsconfig.app.json --noEmit --incremental false
cmd /c npm run build
cmd /c npm run test:e2e
```

Automated tests use offline mock/fake providers and do not spend API credits. Install Chromium once with `cmd /c npx playwright install chromium` in frontend before running browser tests. MySQL locking tests need TEST_MYSQL_URL; without it they are skipped. See the [testing checklist](docs/testing-checklist.md) for isolation, CI, migration coverage and manual acceptance.

## What Makes This Agentic

ResearchMacha uses explicit backend tools instead of a vague autonomous agent. Each workflow records tool inputs, outputs, status, and fallbacks.

Tool steps:

- `plan_search`
- `search_arxiv`
- `rank_candidates`
- `select_candidates`
- `import_papers`
- `analyze_papers`
- `synthesize_brief`

This makes the agent behavior inspectable in the UI and queryable in MySQL.

## Documentation

- [Product specification](docs/product-spec.md): intended researcher experience, feature requirements, and completion criteria.
- [OpenAI setup](docs/openai-setup.md): model settings, optional development reset, credit controls, and startup commands.
- [Showcase](docs/showcase.md): portfolio explanation of agentic RAG, tool use, memory, and vector retrieval.
- [Architecture](docs/architecture.md): system architecture and data flow.
- [Data and recovery](docs/data-and-recovery.md): worker lifecycle, statuses, backups, retry and legacy embeddings.
- [Engineering notes](docs/engineering-notes.md): implementation decisions, challenges and test evidence.
- [Walkthrough](docs/walkthrough.md): demo script and visual assets.
- [Demo](docs/demo.md): local demo setup and troubleshooting.
- [Testing checklist](docs/testing-checklist.md): offline checks and a bounded manual testing pass.

## Known Limitations

- Discovery is limited to arXiv.
- PDFs must be born-digital; OCR is not included.
- Import, analysis, and synthesis run through a database-leased worker in the FastAPI process. Use one backend process; multiple API workers are unsupported.
- Application state and PDFs remain local, but prompts and document text used for generation/embeddings are sent to OpenAI. This is not offline inference.
- Citation validity does not prove scientific interpretation. Model quality, fair comparisons and latency require representative live testing. The app never upgrades models automatically.
- The app is single-user and local-first; no hosted auth is included.
- Reference-heading detection is heuristic; appendices after references are excluded. No PDF passage highlighting/OCR or general stop/cancel control is provided.
- Uploading another copy still creates another library paper; use library selection to reuse existing analysis. Uploaded PDFs may lack bibliographic metadata, which exports do not invent.
- The product specification describes a broader target, including capabilities beyond the supported implementation. Paper notes are supported; collaborative editing and project-level annotation organization are not.
- Memory is intentionally simple; its quality/latency impact has not been formally benchmarked.
