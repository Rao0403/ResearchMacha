# ResearchMacha

ResearchMacha is a local-first research helper system for turning a research question into relevant papers, cited paper notes, cross-paper findings, and suggested next experiments.

## MVP Scope

ResearchMacha is now focused around three showcase workflows:

- `Research`: type one research question, let the backend plan/search/select papers, approve the selected papers, then receive a cited research brief with findings, gaps, experiments, and research directions.
- `Reader`: upload or open one PDF, read it beside structured notes, cited highlights, and a grounded chat panel.
- `Batch Summary`: upload one or more PDFs and get a compact comparison table covering main idea, problem/hypothesis, experiments, models/datasets, results, and conclusions.

## Stack

- Frontend: React, Vite, TypeScript, React Router
- Backend: FastAPI, SQLAlchemy, Alembic, MySQL
- Agent/RAG layer: LangChain with Ollama-first local models
- AI providers: `mock`, `ollama`, and `openai`
- Embeddings: local deterministic fallback for development, provider-backed where available

## Repository Layout

```text
.
|-- api
|   |-- alembic
|   |-- app
|   `-- tests
`-- web
    `-- src
```

## Local Setup

1. Copy `.env.example` to `.env` and fill in your MySQL connection values.
2. Create the MySQL database named in `MYSQL_DATABASE`.
3. Make sure Ollama has a small local model available. The recommended demo model is `llama3.2:1b`.
4. Backend:

   ```bash
   cd api
   python -m venv .venv
   .venv\Scripts\activate
   pip install -e .
   alembic upgrade head
   uvicorn app.main:app --reload --port 8000
   ```

5. Frontend:

   ```bash
   cd web
   npm install
   npm run dev
   ```

6. Open `http://localhost:5173`.

## Demo Flow

1. Open `Research`, enter a research question, and submit.
2. Review the LLM-selected arXiv papers and click `Approve selected papers`.
3. Wait for imported papers to finish analysis and for the final cited brief to appear.
4. Open `Reader`, upload a PDF or paste an existing paper id, then inspect notes/highlights and ask one grounded question.
5. Open `Batch Summary`, upload multiple PDFs, and wait for the comparison table.

Debug/manual project routes still exist under `/debug/...`, but the visible MVP navigation intentionally exposes only the three workflows above.

## AI Providers

- `AI_PROVIDER=mock` gives a deterministic local flow for scaffolding and UI testing.
- `AI_PROVIDER=ollama` uses your local Ollama instance. The default chat model is `llama3.2:1b`.
- `AI_PROVIDER=openai` uses the configured OpenAI key and model.

## Documentation

- `docs/architecture.md` explains the system architecture and agentic RAG pipeline.
- `docs/demo.md` gives the local demo checklist and troubleshooting notes.

## Known Limitations

- V1 assumes born-digital PDFs and does not include OCR.
- Online discovery is limited to arXiv.
- The analysis worker runs in-process through FastAPI background tasks.
- Vector search is implemented in-app for V1 scale rather than using a dedicated vector database.
- LangChain is used as a clear chain layer, not as an autonomous multi-agent loop.
