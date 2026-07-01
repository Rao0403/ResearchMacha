# ResearchMacha

ResearchMacha is a single-user research paper workspace for finding relevant papers, importing PDFs, generating structured reading notes, and chatting with grounded citations.

## V1 Scope

- Search arXiv and import papers directly
- Upload local PDF papers manually
- Persist a personal paper library in MySQL
- Extract text, chunk it, summarize it, and generate cited highlights
- Chat with each paper using retrieval-grounded answers
- Present everything in a focused editorial UI

## Stack

- Frontend: React, Vite, TypeScript, React Router
- Backend: FastAPI, SQLAlchemy, Alembic, MySQL
- AI layer: provider abstraction with `mock`, `ollama`, and `openai` adapters
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
3. Backend:

   ```bash
   cd api
   python -m venv .venv
   .venv\Scripts\activate
   pip install -e .
   alembic upgrade head
   uvicorn app.main:app --reload --port 8000
   ```

4. Frontend:

   ```bash
   cd web
   npm install
   npm run dev
   ```

5. Open `http://localhost:5173`.

## AI Providers

- `AI_PROVIDER=mock` gives a deterministic local flow for scaffolding and UI testing.
- `AI_PROVIDER=ollama` uses your local Ollama instance for summaries, chat, and embeddings.
- `AI_PROVIDER=openai` uses the configured OpenAI key and model.

## Known Limitations

- V1 assumes born-digital PDFs and does not include OCR.
- Online discovery is limited to arXiv.
- The analysis worker runs in-process through FastAPI background tasks.
- Vector search is implemented in-app for V1 scale rather than using a dedicated vector database.

