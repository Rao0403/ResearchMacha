# ResearchMacha

ResearchMacha is a local-first research helper system for turning a research question into relevant papers, cited paper notes, cross-paper findings, and suggested next experiments.

## V1 Scope

- Create research projects from a question or problem statement
- Plan arXiv search queries with a LangChain-powered research planner
- Search arXiv, rank candidates, and import selected papers
- Upload local PDF papers manually
- Persist a personal paper library in MySQL
- Extract text, chunk it, summarize it, and generate cited highlights
- Synthesize findings, gaps, experiments, and research directions across a paper collection
- Chat with each paper using retrieval-grounded answers
- Present everything in a focused research workbench UI

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

1. Open the Projects page.
2. Load the seeded demo project or create a new research question.
3. Generate a research plan.
4. Discover arXiv candidates.
5. Select papers and import them.
6. Wait for individual paper analysis to complete.
7. Generate the cited synthesis brief.
8. Open an imported paper to inspect highlights and ask grounded questions.

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
