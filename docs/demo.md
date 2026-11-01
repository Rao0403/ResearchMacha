# ResearchMacha Local Demo

## Prerequisites

- MySQL running locally.
- OpenAI API key with credit and access to the configured model.
- Python environment installed under `backend/.venv`.
- npm dependencies installed under `frontend/node_modules`.

Follow [OpenAI setup](openai-setup.md) first, including the optional development reset if switching from old provider runs. This demo uses paid API calls; start with one paper rather than approving a full shortlist when checking costs.

## Environment

Create `.env` from `.env.example` and set:

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
QDRANT_MEMORY_COLLECTION=research_macha_memories
```

Create the database in MySQL:

```sql
CREATE DATABASE research_macha;
```

Start Qdrant for the default vector retrieval path:

```powershell
docker compose up -d qdrant
```

Then set:

```env
VECTOR_PROVIDER=qdrant
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=research_macha_chunks
QDRANT_MEMORY_COLLECTION=research_macha_memories
```

Reinstall backend dependencies after pulling this change:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Run

Backend:

```powershell
cd backend
.\.venv\Scripts\python.exe -B -m alembic upgrade head
.\.venv\Scripts\python.exe -B -m uvicorn app.main:app --reload --port 8000
```

Frontend:

```powershell
cd frontend
cmd /c npm ci
cmd /c npm run dev
```

Open:

```text
http://localhost:5173
```

## Demo Script

### Research Workflow

1. Open `Research`.
2. Type a research question and press Enter or click `Start`.
3. Review the recommended arXiv papers selected by the LLM/ranking layer.
4. Optionally unselect weak matches, then click `Approve selected papers`.
5. Check the agent trace and memory signals panel after approval.
6. Wait while the backend imports PDFs, analyzes each paper, and synthesizes the final brief.
7. Inspect cited findings, gaps, suggested experiments, and research directions.

### Paper Reader

1. Open `Reader`.
2. Upload a born-digital PDF, or paste an existing paper id.
3. Wait for analysis if the paper is new.
4. Inspect `Notes`, `Highlights`, and ask one grounded question in `Chat`.

### Batch Summary

1. Open `Batch Summary`.
2. Upload one or more PDFs.
3. Wait for each paper status to become `ready` or `degraded`; inspect any warning.
4. Inspect the overall takeaway and comparison table.

## Troubleshooting

- If synthesis looks generic, inspect generation mode and warnings. `extractive` means source passages were returned after a generation failure; `mock` means explicit fixture mode.
- If embeddings fail, the backend preserves chunks and uses lexical retrieval with a warning; it never silently substitutes hash vectors for a failed OpenAI request.
- If arXiv import fails, check network access and retry with fewer selected papers.
- If MySQL migration fails, verify `.env` and that the database exists.
- If a summary endpoint returns `No analyzed paper evidence`, wait for analysis to become `ready`/`degraded`, or inspect the failed job. A failed required import/analysis blocks research synthesis until Retry or Exclude.
- If Qdrant is down, the app falls back to MySQL retrieval and memory recall. Restart Qdrant and re-analyze papers to populate the vector collections.
- Authentication, quota, configuration, and incomplete-response warnings need investigation before retrying. Retries/reanalysis may incur fresh charges. Review `AI usage:` logs and the OpenAI usage dashboard.
