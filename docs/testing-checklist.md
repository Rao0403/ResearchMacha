# ResearchMacha Testing Checklist

Use this checklist after implementation phases and before recording portfolio media.

## Automated Checks

Backend:

```powershell
cd api
.\.venv\Scripts\python.exe -m pytest
```

Frontend:

```powershell
cd web
cmd /c npm audit --json
cmd /c npm run build
```

Database migrations:

```powershell
cd api
.\.venv\Scripts\alembic.exe upgrade head
```

## Local Services

Start Qdrant:

```powershell
docker compose up -d qdrant
```

Check Qdrant collections after analyzing papers:

```powershell
Invoke-RestMethod http://localhost:6333/collections
Invoke-RestMethod http://localhost:6333/collections/research_macha_chunks
Invoke-RestMethod http://localhost:6333/collections/research_macha_memories
```

Start backend:

```powershell
cd api
.\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8000
```

Start frontend:

```powershell
cd web
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

## Batch Summary Acceptance

Expected behavior:

- Multi-file PDF upload creates one analysis job per file.
- Each paper row shows status.
- Failed paper rows can be retried.
- When all papers are ready, a consolidated summary appears.
- The table includes main idea, problem/hypothesis, experiments, models/datasets, results, and conclusions.
- Paper titles link back to the reader.
- `Export CSV` downloads the comparison table.

## Fallback Acceptance

To test vector fallback, stop Qdrant while `VECTOR_PROVIDER=qdrant`:

```powershell
docker compose stop qdrant
```

Then ask a reader chat question.

Expected behavior:

- The app still answers using MySQL fallback retrieval.
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
