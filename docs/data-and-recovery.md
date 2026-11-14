# Data, recovery and troubleshooting

ResearchMacha supports one local user and one backend process. MySQL and PDF files are the durable workspace. Qdrant is a derived index. A local database does not make inference offline: relevant document text/questions are sent to the configured OpenAI provider.

## Worker lifecycle

| Setting | Default | Meaning |
| --- | --- | --- |
| JOB_WORKER_ENABLED | true | Run the worker from FastAPI lifespan |
| JOB_WORKER_CONCURRENCY | 1 | Worker threads inside that process |
| JOB_WORKER_POLL_SECONDS | 1 | Delay between queue checks |
| JOB_LEASE_SECONDS | 1800 | Time before an unrenewed claim expires |
| JOB_MAX_RECLAIMS | 3 | Claim-attempt limit used during recovery |

Do not run multiple uvicorn workers or multiple API instances against this local worker setup. Startup assumes jobs owned by a previous worker belong to an interrupted local process. Graceful shutdown stops new claims; a process killed during active work relies on recovery. Previously approved jobs may resume and incur API usage when the backend starts.

Completed jobs are not replayed. Interrupted work may repeat an external call if the call finished before its result was committed. Database idempotency and generation checks prevent duplicate active generations and stale replacements; they cannot guarantee exactly-once provider billing.

Reader chat is request-bound. Questions and pending turns are saved before generation. On worker-enabled startup, unfinished assistant turns become failed with a Retry action. Reusing the same completed chat request ID returns its stored answer.

## States and recovery controls

- Papers: queued, processing, ready, degraded, failed.
- Active projects: importing, analyzing, synthesis_queued, synthesizing. Required failures produce blocked; results may finish done or degraded. Discovery also uses draft, awaiting_approval and no_candidates.
- Comparisons: draft, waiting_for_papers, queued, running, blocked, done, degraded or failed.
- Jobs: queued, running, completed, completed_with_warnings, failed or cancelled.

Retry only the affected work. A failed required paper/import prevents research synthesis or comparison completion. Exclude/remove changes that workspace's membership without deleting the library paper or PDF. Library analysis can be shared, so removing one project's link does not cancel another workspace's analysis.

Saving a name, selection, comparison details or personal note does not generate model output. Generating a replacement is explicit. The previous successful result stays available and exports retain its recorded sources. A stale-generation response cannot overwrite a changed evidence set.

## Understanding degraded output

AI means the provider completed generation. Extractive means stored source material was assembled after generation failed. Mock is deterministic demonstration data and is not research evidence. Unknown legacy means provenance was not recorded by an earlier implementation.

Read the warning, not just the status. Embedding outages preserve chunks and allow lexical retrieval. Qdrant outages use compatible SQL vectors where available. Invalid or unavailable evidence cannot authorize unsupported citation IDs. A valid quotation still needs human review for whether it supports the interpretation.

## Preserve and restore work

1. Stop the backend before making a consistent backup; let active work finish if practical.
2. Back up MySQL using your normal database tooling, plus the complete configured upload directory and root environment configuration. Keep credentials private. Exports alone are not a database backup.
3. Restore the database and files to the same installation/path. Stored PDF paths may be absolute; moving the installation requires reviewing/updating those paths deliberately.
4. Apply additive migrations with alembic upgrade head, then restart one backend process. Restore Qdrant's volume if available; otherwise SQL/lexical retrieval remains available until you deliberately rebuild compatible indexes.

The development reset script deletes development data. It is not an upgrade, backup, recovery or routine troubleshooting command. Inspect its help before using it and never use it on work you intend to keep.

Saved personal notes live in MySQL and survive reanalysis. Unsaved drafts are backed up only in that browser tab, not the database; save before closing the tab. Version conflicts keep the draft for manual resolution. Markdown exports include only the saved notes you explicitly select.

## Legacy embeddings and opt-in reanalysis

Migrations do not call models or reanalyze PDFs. Legacy vectors have unknown fingerprints and are not mixed with a new embedding space. Existing summaries remain available and retrieval can use lexical fallback.

To rebuild one paper deliberately:

1. Back up work and confirm the configured provider/model and upload path.
2. Choose a paper ID through Library. Inspect its existing notes first.
3. Use Retry analysis when offered, or explicitly POST to /api/papers/{paper_id}/analyze. This queues a new generation and can incur embedding/generation charges.
4. Wait for a terminal status, inspect warnings and citation coverage, then repeat only for papers that need it.

Do not batch-reanalyze your library merely because an additive migration ran. There is no automatic model escalation or automatic paid legacy migration.

## Hosting boundary

This is a personal local tool. Public hosting requires authentication, paper/project ownership enforcement, rate limits, shared durable file storage, a separate worker deployment and a revised recovery model. Those are not part of this implementation.
