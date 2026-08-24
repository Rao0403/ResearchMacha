# ResearchMacha

![React](https://img.shields.io/badge/frontend-React%20%2B%20Vite-a44f2a)
![FastAPI](https://img.shields.io/badge/backend-FastAPI%20%2B%20SQLAlchemy-24160c)
![LangChain](https://img.shields.io/badge/agent%20layer-LangChain-2f7a55)
![Qdrant](https://img.shields.io/badge/vector%20store-Qdrant%20default-5e8c7b)
![MySQL](https://img.shields.io/badge/database-MySQL-9c6b1f)

ResearchMacha is a local-first research helper system for turning a research question into relevant papers, cited paper notes, cross-paper findings, and suggested next experiments.

It is built as a portfolio-grade MVP around explainable agentic RAG: LLMs handle planning, paper selection, and synthesis; deterministic backend tools handle search, import, parsing, indexing, and persistence.

![ResearchMacha architecture](docs/assets/architecture.svg)

## Core Workflows

- `Research`: type one research question, let the backend plan/search/select papers, approve the selected papers, then receive a cited research brief with findings, gaps, experiments, and research directions.
- `Reader`: upload or open one PDF, read it in a PDF.js viewer beside structured notes, cited highlights, and grounded chat.
- `Batch Summary`: upload one or more PDFs and get a comparison table covering main idea, problem/hypothesis, experiments, models/datasets, results, and conclusions.

![ResearchMacha demo walkthrough](docs/assets/demo-walkthrough.svg)

## Stack

- Frontend: React, Vite, TypeScript, React Router, PDF.js
- Backend: FastAPI, SQLAlchemy, Alembic, MySQL
- Agent/RAG layer: LangChain with Ollama-first local models
- AI providers: `mock`, `ollama`, and `openai`
- Vector retrieval: Qdrant by default with MySQL JSON cosine similarity as fallback
- Memory: MySQL source-of-truth rows indexed into Qdrant for semantic recall, with MySQL fallback

## Repository Layout

```text
.
|-- api
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
`-- web
    `-- src
```

## Quickstart

### 1. Configure Environment

Copy `.env.example` to `.env` and set your MySQL values.

Recommended local settings:

```env
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your-password
MYSQL_DATABASE=research_macha

AI_PROVIDER=ollama
OLLAMA_CHAT_MODEL=gpt-oss:20b-cloud

VECTOR_PROVIDER=qdrant
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=research_macha_chunks
QDRANT_MEMORY_COLLECTION=research_macha_memories
```

Create the database:

```sql
CREATE DATABASE research_macha;
```

### 2. Start Qdrant

```powershell
docker compose up -d qdrant
```

### 3. Start Backend

```powershell
cd api
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[dev]
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8000
```

### 4. Start Frontend

```powershell
cd web
cmd /c npm install
cmd /c npm run dev
```

Open:

```text
http://localhost:5173
```

## Demo Commands

Seed a demo research project with known arXiv candidates:

```powershell
cd api
.\.venv\Scripts\python.exe scripts\seed_demo.py
```

Run checks:

```powershell
cd api
.\.venv\Scripts\python.exe -m pytest

cd ..\web
cmd /c npm audit --json
cmd /c npm run build
```

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

- [Showcase](docs/showcase.md): portfolio explanation of agentic RAG, tool use, memory, and vector retrieval.
- [Architecture](docs/architecture.md): system architecture and data flow.
- [Walkthrough](docs/walkthrough.md): demo script and visual assets.
- [Demo](docs/demo.md): local demo setup and troubleshooting.
- [Testing checklist](docs/testing-checklist.md): acceptance checks before final refinement.

## Known Limitations

- Discovery is limited to arXiv.
- PDFs must be born-digital; OCR is not included.
- Background work runs in-process through FastAPI background tasks.
- The app is single-user and local-first; no hosted auth is included.
- Memory is intentionally simple and becomes useful after repeated workflows.
