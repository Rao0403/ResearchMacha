# Project explanation

ResearchMacha helps a research student discover papers, understand and question their evidence, compare evaluations, preserve personal thinking and export a usable research artifact.

The three main workflows share one reusable paper library. Projects and comparisons have normal navigation and permanent local URLs. The reader restores conversations and position. Personal notes are saved independently of AI summaries. Markdown, BibTeX and CSV exports use stored results without additional inference.

## Application-ready explanation

“I built a local research workspace with React, FastAPI, MySQL and Qdrant. It combines paper discovery, grounded PDF reading and saved comparisons. I separated deterministic ingestion, orchestration and validation from model generation, made long post-approval work recoverable through database leases, and added source provenance, personal notes and exports so the output remains useful beyond a demo.”

## What the implementation demonstrates

- Request-specific structured generation with evidence validation and bounded outputs.
- Explicit tool traces for discovery, selection, import, analysis and synthesis.
- Leased durable jobs, idempotent requests and generation checks against stale results.
- Atomic analysis replacement that preserves prior successful work.
- Embedding-space compatibility checks and usable degraded retrieval.
- Shared papers across independent workspaces, with recovery notifications to dependent projects.
- Versioned chat turns, reading state and personal notes.
- Reopenable artifacts and deterministic, citation-bearing exports.
- Single-flight polling, responsive layouts and keyboard/accessibility checks.

These are engineering capabilities, not proof that generated interpretations are always correct. Citation checks establish identity and valid quotations; researchers still verify relevance and scientific meaning.

## What to discuss in an interview

1. How does a worker recover after a model response but before database persistence?
2. What is idempotent locally, and why can interrupted provider calls still incur duplicate billing?
3. How do generation checks prevent an older synthesis from replacing a changed evidence set?
4. Why are paper analysis and user annotations stored independently?
5. What happens when embedding dimensions or providers change?
6. How do exports preserve the sources of an outdated result?
7. What tests can run offline, and what still needs real-user/model evaluation?
8. Why is a single backend and leased local worker sufficient for this product's supported usage?

See [engineering notes](engineering-notes.md) for evidence and tradeoffs, [architecture](architecture.md) for runtime flows, and [screenshots](walkthrough.md) for fixture UI examples. Public hosting, multi-user security, OCR and collaboration are outside the supported local scope.
