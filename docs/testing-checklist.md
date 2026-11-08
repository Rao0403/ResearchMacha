# ResearchMacha Testing Checklist

Use this checklist after implementation phases and before recording portfolio media.

Automated tests use mock/fake adapters, suppress real API credentials, and block external HTTP. Manual acceptance below uses paid calls when `AI_PROVIDER=openai`. Run one small reader example first, inspect usage, then expand only as needed. Live model evaluation is a user step; no real model results are implied by fixture tests. See [OpenAI setup and credit controls](openai-setup.md).

## Automated Checks

Backend:

```powershell
cd backend
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider
```

Frontend:

```powershell
cd frontend
cmd /c npm test -- --run
cmd /c npm exec tsc -- -p tsconfig.app.json --noEmit --incremental false
cmd /c npm run build
cmd /c npm run test:e2e
```

Database migrations:

```powershell
cd backend
.\.venv\Scripts\python.exe -B -m alembic upgrade head
```

MySQL lock/concurrency tests are skipped without `TEST_MYSQL_URL`. To run them, set that variable to a local MySQL account with permission to create/drop disposable `research_macha_test_*` databases, then run the backend suite. The fixture generates isolated database names and deletes only those databases. Do not point diagnostic SQL/reset commands at valuable data. CI configures a dedicated MySQL service.

## Local Services

Start Qdrant:

```powershell
docker compose up -d qdrant
```

Check Qdrant collections after analyzing papers:

```powershell
Invoke-RestMethod http://localhost:6333/collections
```

Collection names include a 12-character fingerprint suffix, such as `research_macha_chunks_<hash>`. Inspect the names returned above instead of assuming an unsuffixed collection. Legacy spaces are not mixed with new OpenAI vectors.

Start backend:

```powershell
cd backend
.\.venv\Scripts\python.exe -B -m uvicorn app.main:app --reload --port 8000
```

Start frontend:

```powershell
cd frontend
cmd /c npm run dev
```

## Research Workflow Acceptance

Use this question:

```text
What are effective methods for reducing hallucinations in retrieval augmented generation systems?
```

Expected behavior:

- The user only enters a question before approval.
- The agent trace shows `plan_search`, `search_arxiv`, `rank_candidates`, and `select_candidates`.
- Candidate papers are visible with titles, authors, years, scores, and rationales.
- Approval imports papers and queues analysis.
- The workflow polls until paper analysis finishes.
- The final brief includes cited findings, gaps, suggested experiments, and research directions.
- Fallback notices are visible if any model/retrieval fallback occurs.
- Memory signals appear after approval and analysis.
- Failed required imports/analyses block synthesis. Retry resumes failed work; Exclude removes only project membership/candidates, retaining library papers.
- GET polling does not start model calls or change state. Generation warnings and degraded/mock/legacy modes are visible.

MySQL checks:

```sql
SELECT tool_name, status, error_message
FROM agent_steps
ORDER BY created_at DESC, position
LIMIT 20;

SELECT scope, memory_type, source, LEFT(text, 180) AS preview
FROM research_memories
ORDER BY created_at DESC
LIMIT 20;
```

## Reader Acceptance

Expected behavior:

- Uploading a born-digital PDF creates an analysis job.
- PDF.js renders the paper, not a browser iframe.
- Page navigation and zoom controls work.
- Notes show all required structured sections.
- Highlights include supporting excerpts and page numbers.
- Clicking note/highlight/chat citations jumps to the cited PDF page.
- Chat answers cite source pages.
- Failed analysis can be retried from the reader.
- A failed reanalysis keeps the previous successful notes visible.
- Check a later-page claim as well as an abstract claim; grounded citations do not by themselves prove full-document coverage or semantic accuracy.
- Verify body text before a references heading on a shared page remains available, while bibliography entries and appendices after references are excluded from retrieved evidence. Keep a PDF containing a contents page in the regression set.

## Batch Summary Acceptance

Expected behavior:

- Multi-file PDF upload creates one analysis job per file.
- Each paper row shows status.
- Failed paper rows can be retried.
- When all papers are ready/degraded, a consolidated summary appears and degradation warnings are visible.
- The table includes main idea, problem/hypothesis, experiments, models/datasets, results, and conclusions.
- Paper titles link back to the reader.
- `Export CSV` downloads the comparison table.
- Each requested paper appears exactly once; cells are concise, titles match source records, and unsupported comparisons are acknowledged. Retry live model testing with the unchanged 6,000-token output cap before considering any increase.

## Fallback Acceptance

To test vector fallback, stop Qdrant while `VECTOR_PROVIDER=qdrant`:

```powershell
docker compose stop qdrant
```

Then ask a reader chat question.

Expected behavior:

- The app still answers using MySQL fallback retrieval.
- If compatible embeddings are unavailable, lexical/initial-chunk retrieval is explicitly labelled; no silent hash embeddings replace a failed provider call.
- A fallback notice is visible in the response or trace.

Restart Qdrant:

```powershell
docker compose start qdrant
```

## Memory Acceptance

After approving papers in one workflow, ask a related second question:

```text
What evaluation methods are used to measure factuality in retrieval augmented generation systems?
```

Expected behavior:

- The agent trace reports memory signals.
- Candidate selection can show memory-adjusted scoring.
- The memory panel shows accepted/rejected/preference/fact signals.
- The second workflow should lean toward previously approved themes and away from rejected weak matches.
