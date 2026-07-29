# ResearchMacha Local Demo

## Prerequisites

- MySQL running locally.
- Ollama installed.
- `llama3.2:1b` available in Ollama.
- Python environment installed under `api/.venv`.
- npm dependencies installed under `web/node_modules`.

Check local Ollama models:

```powershell
ollama list
```

The preferred model line is:

```text
llama3.2:1b
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
OLLAMA_CHAT_MODEL=llama3.2:1b
```

Create the database in MySQL:

```sql
CREATE DATABASE research_macha;
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

1. Click `Load demo`.
2. Open the created project.
3. Review generated queries and inclusion criteria.
4. Run `Search arXiv` if candidates are not already present.
5. Select 3 candidates and click `Import selected`.
6. Wait for paper analysis status to become `ready`.
7. Click `Generate brief`.
8. Inspect cited findings, gaps, suggested experiments, and directions.
9. Open one paper from the collection and inspect highlights/chat.

## Troubleshooting

- If synthesis looks generic, confirm `AI_PROVIDER=ollama` and Ollama is running.
- If embeddings fail because `nomic-embed-text` is not available, the backend falls back to deterministic embeddings for the MVP.
- If arXiv import fails, check network access and retry with fewer selected papers.
- If MySQL migration fails, verify `.env` and that the database exists.
