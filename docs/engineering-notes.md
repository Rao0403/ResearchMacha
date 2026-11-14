# Engineering decisions and evidence

These notes describe the current implementation and its tradeoffs. They do not infer historical intent or claim unrun performance experiments.

| Decision | Why it fits this product | Tradeoff / evidence |
| --- | --- | --- |
| One modular FastAPI backend | Simple local operation and transactions across related work | Multiple API processes are unsupported with startup recovery; services/jobs.py |
| MySQL-leased in-process worker | Approved long work survives tab closure and process interruption | An interrupted external call may be billed again; tests/test_mysql_integration.py and test_job_worker.py |
| Generation-based replacement | Prior notes/results remain readable and stale responses cannot replace edited work | Derived vectors may briefly outlive their SQL generation; tests/test_analysis_generations.py, test_artifact_provenance.py |
| Embedding-space fingerprints | Provider/model/dimension changes cannot silently mix incompatible vectors | Legacy data uses lexical retrieval until deliberate reanalysis; services/retrieval.py and vector_store.py |
| Short evidence IDs in bounded model drafts | Keeps output focused while the backend owns titles, pages and quotations | Valid IDs do not prove semantic entailment; tests/test_batch_generation.py and test_comparison_evidence.py |
| Library papers shared across workspaces | Ready analysis can be reused without repeat ingestion/analysis charges | Reanalysis changes current evidence generation, so old artifacts must retain their own source metadata; test_library_reuse.py |
| Personal notes independent of AI summaries | Reanalysis cannot overwrite the researcher's own work | Conflicting edits need manual resolution; test_personal_notes.py |
| Deterministic read-only export | Useful artifacts can be downloaded without another model call | Missing metadata and legacy provenance cannot be reconstructed by inference; test_exports.py |

## Challenges addressed

**Interruptions between phases.** Leases and attempt limits recover work. Atomic SQL swaps and completed-generation detection avoid repeating committed analysis. The remaining limit is a provider call whose response was never persisted.

**Concurrent edits and stale sessions.** Row locks serialize claims/target changes; version counters reject conflicting reading-state/note edits. Synthesis refreshes the locked project before its generation check. Cross-session tests verify that an older result cannot overwrite newer evidence.

**Provider and retrieval failures.** Typed failures, bounded repair, source-extractive output and lexical retrieval keep failures visible. Successful prior analysis/results are retained where replacement fails. Hard extraction or database errors remain failures; required evidence is not silently omitted.

**Maintaining source identity after editing a workspace.** New artifacts snapshot the question/goal, creation time, paper metadata and analysis generations. Exports use that record. Legacy exports explicitly identify missing provenance instead of substituting a newer edited goal.

**Preventing user-work loss.** Chat questions are persisted before generation. Notes have independent storage, explicit saves, conflict checks and browser-tab draft backup. Read-only reopening/polling never starts a new generation.

**Testing without spending credits.** Tests remove API credentials from their process and reject external HTTP. A fake-provider journey executes real ingestion, leased dispatch, persistence, reuse, notes and exports. MySQL tests cover actual locking/migrations; Playwright covers interaction and downloads. These do not evaluate live scientific interpretation or provider latency.

## Evaluation boundaries

No comparison of models, rerankers, memory strategies or throughput was run during export completion. User-reported successful reader/comparison/research testing informed the product direction, but is not a reproducible benchmark. Future model/retrieval changes should use a fixed paper/question set and measure groundedness, citation relevance, latency, tokens and failure rate before changing architecture or budgets.

Keep the current database, monolith, file storage, provider interface and simple orchestration for the supported local scope. More agents, services or queue infrastructure have no demonstrated requirement here.
