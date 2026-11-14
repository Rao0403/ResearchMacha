# OpenAI setup and development reset

## Defaults and scope

ResearchMacha now uses the native OpenAI Python SDK. Generation uses the Responses API with strict JSON schemas and the existing evidence validators. Embeddings use the embeddings API. The React application sends requests only to FastAPI; it never receives the OpenAI key.

The initial configuration favors cost. These choices are starting points for user testing, not measured quality or latency results:

| Setting | Default | Purpose |
| --- | --- | --- |
| `AI_PROVIDER` | `openai` | Use `mock` only for explicit offline fixtures |
| `OPENAI_MODEL` | `gpt-6-luna` | All generation operations; no automatic model escalation |
| `OPENAI_EMBED_MODEL` | `text-embedding-3-small` | Document and query embeddings |
| `OPENAI_REASONING_EFFORT` | `none` | Initial low-cost, low-latency setting |
| `AI_CHAT_TIMEOUT_SECONDS` | `180` | Timeout per generation HTTP request |
| `AI_EMBEDDING_TIMEOUT_SECONDS` | `60` | Timeout per embedding HTTP request |
| `AI_PLAN_MAX_OUTPUT_TOKENS` | `1500` | Planning and candidate selection |
| `AI_SUMMARY_MAX_OUTPUT_TOKENS` | `4000` | Paper notes and highlights |
| `AI_CHAT_MAX_OUTPUT_TOKENS` | `1500` | One reader answer |
| `AI_SYNTHESIS_MAX_OUTPUT_TOKENS` | `6000` | Research brief |
| `AI_BATCH_MAX_OUTPUT_TOKENS` | `6000` | Batch comparison |

Output limits apply per attempt, not to a complete workflow. Input text, embedding requests, repair attempts, memory operations, and explicit retries also consume tokens. These controls are not a hard dollar cap. Consult the [official API pricing](https://openai.com/api/pricing/) and [usage dashboard](https://platform.openai.com/usage) for current prices and actual spending.

## One-time setup or provider switch

Run from `D:\Aryan\ResearchMacha`. Keep an existing `.env`; copy only when creating a fresh environment:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose up -d qdrant
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Set these entries in the repository-root `.env` using your editor:

```env
AI_PROVIDER=openai
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=gpt-6-luna
OPENAI_EMBED_MODEL=text-embedding-3-small
OPENAI_REASONING_EFFORT=none
UPLOAD_DIR=backend/uploads
```

Set MySQL credentials as well. `DATABASE_URL`, when present, overrides `MYSQL_*`. Create the `research_macha` database in MySQL if needed. Remove obsolete `OLLAMA_*` and `AI_MAX_OUTPUT_TOKENS` entries to avoid confusion; they are no longer used. `.env.local` overrides `.env`; environment variables override both files.

If an existing virtual environment was moved with the renamed folder, refresh it using `python -m venv --upgrade .venv`, then reinstall the editable package using the command above. Use `python.exe -m ...` commands rather than old executable launchers containing the former directory path.

### Optional development reset

This is destructive cleanup for disposable development data, not an upgrade or recovery procedure. Back up valuable work and use additive migrations instead. The reset clears ResearchMacha rows, including saved results, personal notes, jobs, projects, chat and memories, plus the configured legacy/fingerprinted Qdrant collections. It retains schema/Alembic revision, unrelated tables/collections, configuration and PDF files in `backend/uploads`. Retained files alone cannot restore the deleted notes or results.

Stop the backend first. With MySQL and Qdrant running, execute from `backend`:

```powershell
.\.venv\Scripts\python.exe -B -m alembic upgrade head
# Preview: lists only application row counts and matching vector collection names.
.\.venv\Scripts\python.exe -B -m scripts.reset_development
# Apply only when you intend to discard these development runs:
.\.venv\Scripts\python.exe -B -m scripts.reset_development --apply --confirm research_macha
```

The command requires `APP_ENV=development`, local services, and a database named `research_macha` or `research_macha_*`. `--confirm` must match the actual configured database name. It does not call an AI provider. Qdrant and SQL cannot share a transaction: vectors are cleared first, SQL deletes are transactional, and an interrupted reset can be rerun. Fix service connectivity or run migrations if the preview fails; do not bypass the guards.

The worker refuses startup when queued/running jobs were created by the previous provider or lack provider metadata. This prevents an old run from unexpectedly spending credits on restart. Preserve the original database and files; use a separate development database/collection names when changing providers. Worker-disabled startup can serve saved data without replaying jobs. Reset only when you explicitly intend to discard that database's development work. Existing completed results alone do not trigger regeneration.

## Start the app

Start MySQL through your installed MySQL service. In a terminal at the repository root:

```powershell
docker compose up -d qdrant
cd backend
.\.venv\Scripts\python.exe -B -m alembic upgrade head
.\.venv\Scripts\python.exe -B -m uvicorn app.main:app --reload --port 8000
```

In a second terminal at the repository root:

```powershell
cd frontend
cmd /c npm ci
cmd /c npm run dev
```

Open `http://localhost:5173`. Future starts can skip `npm ci` unless dependencies changed. Missing keys fail startup without a model request. Key validity and account/model access are checked only by your first actual operation; no paid startup probe is performed. The worker resumes current-provider pending jobs, so stop the backend to pause queued work. Run one API process; do not add `--workers`.

## Credit controls and evaluation

- Automated checks and export completion use no live API evaluation or automatic reanalysis.
- SDK retries are disabled. Each structured operation makes at most two generation requests: one initial request and, only for output validation or rate limiting, one repair/retry. Authentication, quota, configuration, timeout, refusal, incomplete-output, and service failures do not trigger that retry.
- A workflow includes multiple operations and can include multiple papers. The two-attempt limit is not a workflow-wide request limit. Worker recovery and manually pressing Retry/Reanalyze can initiate new operations.
- Generation requests use `store=false`. No OpenAI search tools, hosted file uploads, or background Responses jobs are used. Document text still leaves the machine for generation and embeddings; `store=false` is not a claim of zero data retention.
- Terminal entries beginning `AI usage:` report operation, model, attempt, elapsed time, request ID when supplied, token totals, cached tokens, and reasoning tokens when supplied. Embedding logs include batch size and actual input tokens. Prompts, PDF text, API keys, and estimated dollar charges are not logged.
- Start manual testing with one short PDF and one chat question. Check notes and citations against the PDF and inspect actual usage before trying multi-paper synthesis. Reuse processed library papers. Review quality and usage before changing models or budgets.
- Output-token limits may produce an explicitly degraded result if too low; they never cause an automatic upgrade to a more expensive model. Increase a budget or change the model only after reviewing an actual failure.

## Offline checks

These commands use mocks and fixture responses; they do not call OpenAI, arXiv, or a live Qdrant service:

```powershell
cd backend
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider
cd ..\frontend
cmd /c npm test -- --run
cmd /c npm run build
```

MySQL-specific tests create disposable databases; see [testing checklist](testing-checklist.md). Offline checks do not establish real model quality or latency. See [workflows and exports](demo.md) and [data preservation/recovery](data-and-recovery.md).

## Troubleshooting

- Missing key: add `OPENAI_API_KEY` to the root `.env`; never a `VITE_` variable. Restart the backend after changing settings.
- Authentication/quota errors: verify the API project key, billing, and access in the OpenAI dashboard. Repeated Retry clicks do not solve exhausted credit.
- Invalid model/schema: the app displays a configuration warning. Preserve the error and operation name for diagnosis rather than repeatedly rerunning the workflow.
- Degraded notes/chat: the app may show literal source excerpts when generation fails. They are usable evidence, not a successful AI summary. Existing successful analysis is retained on a failed reanalysis.
- Missing embeddings/Qdrant outage: retrieval uses compatible SQL embeddings or lexical/initial-chunk fallback with a warning. OpenAI and old provider vectors are not compared together.
- Old-provider queued jobs: stop the backend, preserve the original data and read the recovery guidance. Do not reset valuable work merely to pass the startup guard. No automatic provider conversion or regeneration occurs.
