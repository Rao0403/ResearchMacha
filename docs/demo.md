# Using ResearchMacha

Follow the [README setup](../README.md#quickstart). Run one backend process and one frontend dev server. Generation and embedding actions use API credits; opening saved results, saving personal notes and exporting do not.

## Research: question to evidence

1. Open Research. Try: **How do retrieval-augmented methods improve factual accuracy in domain-specific question answering?**
2. Leave the library selection empty to discover arXiv papers. Review relevance before approval; at most five evidence papers are supported.
3. Save a changed selection if you want to return before approval. Saving does not import papers.
4. Approve selected papers. Follow import, analysis and synthesis progress. A failed required item shows a blocker; Retry repeats failed work, Exclude changes the evidence set.
5. Read the brief's findings, evidence, gaps and proposed experiments separately. Follow a citation and verify its page and passage.
6. Name the project. Reopen it through Projects, not a debug route.
7. Alternatively, select ready library papers when entering the question to synthesize those sources without discovery/reanalysis.
8. Adding library evidence to a saved project preserves its previous brief. Use Generate updated brief explicitly when ready.

Discovery/selection are synchronous API work; durable background work starts after approval. Closing the browser does not stop the backend worker.

## Reader

1. Upload a born-digital PDF or open a paper through Library or a citation. PDFs remain readable during analysis.
2. Inspect AI Notes and Highlights, including methods/results later in the body. Expand View passage to read a citation excerpt.
3. In Chat, ask: **Which datasets, metrics and baselines support the main result? What did the study not test?**
4. Ask a follow-up, then reopen the paper. Saved conversations and reading position should return. New conversation starts a separate thread.
5. In My Notes, write a critique or experiment idea. Attach the current page or the selected source passage, then Save note.
6. Edit or delete saved notes explicitly. A conflict retains your draft; reload saved notes to resolve it. Unsaved drafts belong to the browser tab, so save before closing it.
7. Retry analysis only when needed; this can incur new generation/embedding charges. Personal notes are not replaced.

## Comparison

1. Open Compare. Select two to ten PDFs, library papers, or a mixture.
2. Give the comparison a name and goal, such as **Compare evaluation datasets, metrics, baselines and evidence for generalization.**
3. Submit once. The saved URL survives refresh/tab closure; the worker waits for required analyses.
4. Review eight dimensions: idea, hypothesis, experiments, models/datasets, results, conclusions, limitations and evaluation conditions.
5. Compare conditions before interpreting scores. Different datasets or metrics do not establish a universal winner.
6. Expand a passage and open its paper/page. Back to evidence returns to the saved result.
7. Edit the goal or add library papers with Save details. Use Update comparison explicitly; the old result stays readable meanwhile.
8. Retry failed paper processing or remove it when at least two papers remain. A required failed paper is never silently omitted.

## Export

Open Export in Reader, Research or Compare.

- Download Markdown exports the stored notes/brief/comparison, citations, references and warnings.
- Check only the saved personal notes you want included. Drafts are not exported. Refresh saved notes and options if you saved another note while the panel stayed open.
- Download BibTeX exports recorded bibliographic metadata. Uploaded PDFs often lack authors/year; review these references rather than treating missing fields as inferred facts.
- Comparisons also provide Download CSV, including dimensions and source provenance.
- Exports do not call models. Outdated results keep their recorded goal and sources; legacy gaps are explicitly labelled.
- PDF links open the configured application origin (localhost by default) while that installation is running. Public arXiv links and bibliographic text remain useful elsewhere.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| No extractable text | Inspect the PDF; scanned pages require OCR, which is outside scope. |
| Processing fails | Inspect its error/warning and Retry the affected item. Preserve successful papers. |
| Project blocked | Resolve or exclude every required failure before synthesis. |
| Incomplete response / token limit | Inspect the provider error; retry is explicit. No model/budget escalation occurs automatically. |
| Qdrant unavailable | Compatible SQL vectors or lexical retrieval remain available with warnings. |
| Old provider jobs on startup | Do not reset valuable data. Read [data and recovery](data-and-recovery.md) and the development-only reset help. |
| Saved page or note conflict | Another request changed the version. Reload the saved version; keep/copy the local draft first. |
| Missing source metadata | Review the reference manually. Exports do not invent DOI, journal, authors or publication details. |

Use the [testing checklist](testing-checklist.md) for a complete manual pass and [recovery guide](data-and-recovery.md) for backups.
