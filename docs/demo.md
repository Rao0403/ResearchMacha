# ResearchMacha Local Demo

## Prerequisites

- MySQL running locally.
- Ollama installed.
- `gpt-oss:20b-cloud` available through Ollama.
- Python environment installed under `api/.venv`.
- npm dependencies installed under `web/node_modules`.

Check local Ollama models:

```powershell
ollama list
```

The preferred model line is:

```text
gpt-oss:20b-cloud
```

## Environment

Create `.env` from `.env.example` and set:

```env
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your-password
MYSQL_DATABASE=research_macha
AI_PROVIDER=ollama
OLLAMA_CHAT_MODEL=gpt-oss:20b-cloud
VECTOR_PROVIDER=qdrant
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
```

Reinstall backend dependencies after pulling this change:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .[dev]
```

## Run

Backend:

```powershell
cd api
.\.venv\Scripts\python.exe -m pip install -e .[dev]
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8000
```

Frontend:

```powershell
cd web
cmd /c npm install
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
5. Wait while the backend imports PDFs, analyzes each paper, and synthesizes the final brief.
6. Inspect cited findings, gaps, suggested experiments, and research directions.

### Paper Reader

1. Open `Reader`.
2. Upload a born-digital PDF, or paste an existing paper id.
3. Wait for analysis if the paper is new.
4. Inspect `Notes`, `Highlights`, and ask one grounded question in `Chat`.

### Batch Summary

1. Open `Batch Summary`.
2. Upload one or more PDFs.
3. Wait for each paper status to become `ready`.
4. Inspect the overall takeaway and comparison table.

## Troubleshooting

- If synthesis looks generic, confirm `AI_PROVIDER=ollama` and Ollama is running.
- If embeddings fail because `nomic-embed-text` is not available, the backend falls back to deterministic embeddings for the MVP.
- If arXiv import fails, check network access and retry with fewer selected papers.
- If MySQL migration fails, verify `.env` and that the database exists.
- If a summary endpoint returns `No analyzed paper evidence`, wait for the paper statuses to become `ready`.
- If Qdrant is down, the app falls back to MySQL retrieval. Restart Qdrant and re-analyze papers to populate the vector collection.
