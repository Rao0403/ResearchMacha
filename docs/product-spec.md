# ResearchMacha product specification

Created: 26 October 2026

Purpose: define the complete product we are building, from the researcher's point of view. This is the reference for feature behavior, product decisions, and user acceptance testing. It describes the intended finished experience; it does not claim that every requirement is already implemented.

Implementation and testing happen together against this specification. A discovered defect becomes work to resolve. An agreed improvement becomes a requirement here and is carried through to a usable result. Engineering plans explain how to meet these requirements; they do not replace them.

## 1. Product purpose

ResearchMacha helps a student or researcher turn a research question and a collection of papers into an evidence-backed understanding they can inspect, question, annotate, compare, and reuse in their own research.

The user should finish a session knowing:

- Which papers are relevant to their question and why.
- What each paper actually studies, how it was evaluated, and what it establishes.
- Where the supporting evidence appears in the original papers.
- Where papers agree, differ, or cannot fairly be compared.
- What remains uncertain and which follow-up investigations would be useful.
- What the user thinks about the evidence, preserved separately from generated content.

The resulting notes, comparison, and brief should be useful in a literature review, project proposal, supervisor discussion, experiment plan, or research presentation.

The product promise is: **find relevant papers, understand the evidence, preserve your thinking, and produce a research artifact you can defend.**

## 2. Intended users and real tasks

The primary user is a research student, final-year project student, or early-career researcher working independently. A fellow student should be able to set up their own workspace and complete these tasks without needing a guided demonstration from the developer.

| Situation | What the user needs | A useful outcome |
| --- | --- | --- |
| Starting an unfamiliar topic | Find a manageable set of relevant papers and understand the terminology | A reviewed shortlist with clear relevance explanations |
| Reading an important paper | Understand its methods, evaluation, contribution, and limitations | Cited notes and answers that lead back to the PDF |
| Choosing a project approach | Compare evidence across several papers | A comparison that identifies meaningful differences and comparability limits |
| Preparing a supervisor meeting | Explain findings, uncertainties, and possible next steps | A concise brief with references and personal notes |
| Returning after several days | Recover the question, sources, conversation, and prior thinking | A saved workspace that can be continued |

## 3. Principles for product decisions

1. Evidence should be easy to inspect. A claim should lead to its paper, page, and supporting passage.
2. Useful research assistance includes saying that the available papers do not answer the question.
3. Generated interpretation, quoted source material, and researcher-authored notes must be visibly distinct.
4. Users control the evidence set and research direction. Suggestions need understandable reasons.
5. Useful completed work survives a failure, refresh, navigation, or interrupted session.
6. Waiting must be understandable. Users can see the current activity, elapsed time, remaining work, and available actions.
7. A recovered or partial result is described honestly. A warning must explain its practical effect.
8. The interface is calm, consistent, and comfortable for sustained reading on an ordinary laptop.
9. A feature earns its place by helping users understand, verify, compare, preserve, or communicate research.

## 4. Scope of the complete product

The finished product includes these connected capabilities:

| Area | Required capability |
| --- | --- |
| Research | A saved journey from question through paper selection to a cited brief |
| Reader | A useful PDF reader with cited notes, highlights, grounded chat, and personal annotations |
| Comparison | A saved comparison across uploaded or existing papers, with evidence and meaningful differences |
| Library | A searchable collection of reusable papers, with understandable processing and reading states |
| Projects | Saved questions, evidence selections, findings, comparisons, and researcher notes |
| Export | Readable briefs and notes, comparison data, and bibliographic references |
| Progress and recovery | Visible activity and elapsed time, understandable partial results, retries, exclusions, and stopping work |

The supported research scope is scholarly discovery through arXiv and the user's own text-based PDFs. The product must clearly identify this search boundary. It must not imply that searching arXiv establishes a complete or systematic review of the literature.

The completed product is a personal workspace that other researchers can run for themselves. Shared accounts, simultaneous collaborative editing, public hosting, automatic access to paywalled papers, and scanned-document recognition are outside this scope. These boundaries do not excuse incomplete behavior within the supported workflows.

## 5. Research: from question to evidence brief

### 5.1 Start with the user's actual question

**R1. Question and scope.** The user can enter a natural-language research question. Optional context can explain the domain, task, date range, or comparison they care about. They can start with a question alone when its meaning is clear.

**R2. Resolve material ambiguity.** If an unexplained acronym or term would substantially change the search, the product asks for clarification before presenting a confident answer. It shows any interpretation it is using. It must not silently replace an unfamiliar term with a better-known one.

Example: for "How effective is JEV in classification tasks compared with LLMs?", an unresolved meaning of "JEV" should prompt the user to expand it or provide a relevant paper. A clear question should proceed without unnecessary questions.

**R3. Preserve the question.** The question is saved with the project, along with the actual search scope. Refining it preserves the previous brief until the replacement is ready and identifies that the existing result answers an earlier question.

### 5.2 Review the paper shortlist

**R4. Inspectable candidates.** Each candidate shows title, authors, year when known, abstract, source link, and a specific relevance explanation. Relevance suggestions explain why a paper helps answer this question. They are not presented as scientific quality scores.

**R5. User approval.** The user can open a paper's source, select or deselect candidates, and approve a clearly counted set. The product supports up to five active papers in a research run and communicates that limit before approval.

**R6. Weak or empty discovery.** A search with weak or no matches explains the limitation and offers concrete ways to refine the question. It must not fill the shortlist with irrelevant papers to reach a desired count.

**R7. Bring existing evidence.** A project can include papers already in the library or uploaded by the user. The user does not have to rediscover a known paper or upload it again to use it in research.

**R8. Review the evidence set.** The approved papers remain visible throughout processing and in the final brief. Excluded and unavailable papers are distinguishable from the papers actually used. Previous preferences must not silently hide relevant alternatives; users can run a search without prior selection preferences.

### 5.3 Receive an answer with appropriate limits

**R9. Answer the question directly.** The brief begins with a concise answer explaining what the selected evidence supports, what it does not establish, and the main qualifications. If a direct comparison is absent, the answer says so.

**R10. Brief contents.** The brief includes:

- The question and scope.
- The papers actually used, with links to their readers.
- Key findings with supporting citations.
- An evidence overview describing each paper's relevant method, evaluation, and result.
- Agreements, apparent conflicts, and important comparability differences.
- Evidence gaps and limitations.
- Suggested experiments or directions when the evidence supports a useful proposal.
- Relevant researcher notes and a bibliography.

Sections with insufficient evidence show that explicitly. They do not contain generic filler to make the brief appear complete.

**R11. Findings and proposals are different.** Reported results are identified as findings. An experiment proposed by ResearchMacha is identified as a suggestion, with its motivation, question, comparison, and possible measurement. A citation motivates the proposal; it must not imply that the paper already performed it.

**R12. Revise the evidence deliberately.** Users can add or exclude a paper, see that the previous brief needs updating, and request a revised brief. The replacement identifies its evidence set. The previous successful brief remains readable while work continues or if replacement fails.

## 6. Reader: understand one paper and verify its claims

### 6.1 Open and read

**P1. Start naturally.** Users can upload a PDF, open a library paper, or follow a citation from research or comparison. Knowing an internal paper identifier must not be necessary.

**P2. Read while analysis runs.** A valid PDF becomes readable as soon as it is available. Generating notes does not prevent paging, zooming, or reading. The paper is visually dominant, and the notes/chat area remains comfortable at common laptop widths.

**P3. Keep reading context.** Reopening a paper restores the reading position, personal notes, and saved chat. Moving to another paper immediately replaces the old paper's title, notes, conversation, and citation target. The product never shows one paper's content under another paper's identity.

**P4. Unsupported documents.** Invalid, inaccessible, or non-readable PDFs receive a clear explanation. A scanned PDF that cannot be read must not be presented as successfully understood. Visible upload limits are checked before the user waits for analysis.

### 6.2 Generated reading notes

**P5. Six useful sections.** Notes explain:

1. Problem or hypothesis.
2. Approach and contribution.
3. Experiments and evaluation setup.
4. Results, including important quantitative evidence when available.
5. Conclusion and what the results establish.
6. Limitations, assumptions, and unresolved questions.

**P6. Body coverage.** Notes account for evidence across the paper's main body. An abstract alone is insufficient when detailed methods, results, and limitations are available later. References are not mistaken for the paper's findings. Relevant appendices can be cited and identified as supplementary evidence.

Coverage is not measured by forcing a different citation page into every section. The cited passage must support the content. The reader identifies any material extraction or coverage limitation rather than claiming to have understood inaccessible content.

**P7. Specific evidence.** Results preserve metric names, units, datasets, comparison conditions, and qualifications when reported. A generated number must be traceable to the source. Missing information is labelled "not reported" or "not found in the available evidence," with those meanings kept distinct.

**P8. Honest uncertainty.** Unavailable sections are marked individually. A failure affecting one section should preserve validated sections wherever possible. Existing useful notes remain readable during retry or reanalysis.

### 6.3 Highlights and source navigation

**P9. Meaningful highlights.** Highlights identify important contributions, results, assumptions, or limitations. Each has a short explanation and a source passage. They should help decide what to read closely, rather than merely repeating the first paragraphs.

**P10. Useful citations.** A compact citation reveals the source page and excerpt. Selecting it opens the correct paper and page without losing the current question or notes. When exact passage emphasis is available, it identifies the cited text; otherwise page navigation and a readable excerpt remain available.

### 6.4 Chat with the paper

**P11. Focused questions.** Users can ask about methods, definitions, assumptions, experiments, results, or limitations and ask follow-up questions within the same paper conversation.

**P12. Grounded answers.** Claims about the paper have supporting citations. An answer distinguishes reported facts from interpretation. It states when the available passages do not answer the question and must not invent a result, dataset, or experiment.

**P13. Understandable follow-ups.** A follow-up such as "What baseline did they compare against?" uses the relevant conversation context. Starting a new conversation is an explicit action. Chat history survives leaving and reopening the paper.

**P14. Waiting and failure.** While an answer is being prepared, users see that state and cannot accidentally submit the same request repeatedly. A failed answer preserves the question, prior messages, and draft input, with a clear retry action.

### 6.5 Preserve the researcher's own thinking

**P15. My notes.** Users can create, edit, and delete personal notes attached to a paper and optionally a page or cited passage. They can record a critique, question, implementation idea, or experiment hypothesis.

**P16. Ownership is visible.** Personal notes are visually distinct from generated notes and source quotes. The user can tell whether an edit is saved. Generating new AI notes never overwrites personal annotations.

**P17. Reuse notes.** Users can find their annotations when returning to a paper, include selected notes in a project or export, and preserve the source link alongside their commentary.

## 7. Comparison: understand differences across papers

**C1. Select a collection.** Users can choose existing library papers, upload PDFs, or combine the two. A comparison supports up to ten papers. Comparing one paper offers the reader as the more useful starting point; at least two are needed for cross-paper conclusions.

**C2. State the comparison goal.** Users can explain what they are comparing, such as training efficiency, classification performance, robustness, or data requirements. This goal affects emphasis without allowing unsupported claims.

**C3. A useful research matrix.** Papers retain visible identities while users scan these dimensions:

- Research question and domain.
- Method and model family.
- Training or adaptation requirements, when reported.
- Datasets, task definitions, and evaluation setup.
- Baselines and metrics.
- Key results, with values and qualifications where supported.
- Computational or data cost, when reported.
- Limitations and assumptions.
- Relevance to the user's stated goal.

Important factual cells provide citations. Missing values are explicit; they are not invented or copied from another paper.

**C4. Synthesis beyond the matrix.** A short overview identifies meaningful agreements, differences, and remaining uncertainties. Every factual cross-paper claim identifies its supporting papers.

**C5. Fair comparisons.** Scores from different datasets, task definitions, splits, or metrics are not used to declare a universal winner. The product explains why results are or are not directly comparable. Contradictions are distinguished from different experimental conditions.

**C6. Inspect and preserve.** Users can open supporting passages, save the comparison to a project, reopen it, add their own notes, change the goal or evidence set, and export the result. Existing output stays readable while a replacement is prepared.

**C7. Partial processing.** Ready papers stay available if another fails. Users can retry or exclude the failed paper. A final comparison never silently omits an approved paper. A deliberately partial comparison identifies excluded or unavailable evidence.

## 8. Library and project organization

**L1. Reusable collection.** Every successfully saved paper can be found in the library and reused in reading, research, and comparison without uploading another copy. Existing matching papers are identified when possible instead of silently multiplying identical entries.

**L2. Find a paper.** Users can search by title, author, or known topic text; filter by analysis state and project; and sort by recent use or date. Rows show paper identity, available metadata, warnings needing attention, and a clear open action.

**L3. Saved projects.** Users can create and name a project around a research question. A project brings together its papers, selection decisions, brief, comparisons, and personal notes. Saved projects are reachable through the normal navigation.

**L4. Resume work.** Users can reopen an unfinished or completed project after refresh, browser closure, or application restart. The saved question, evidence selection, current progress, and existing outputs are restored. A browser tab must not be the only way to find an active run.

**L5. Safe removal.** Removing a paper from a project does not delete it from the library or remove it from other projects. Permanent library deletion is an explicitly named, confirmed action that explains what will be removed and what existing artifacts will lose access to. Nothing is deleted merely because it was excluded from an analysis.

**L6. Clear empty states.** Empty libraries and projects offer a relevant next action, such as uploading a paper or asking a question, without directing users to hidden or obsolete screens.

## 9. Export useful research artifacts

**E1. Brief and reading notes.** Users can export a research brief or a paper's notes as readable Markdown. Export includes the question or paper identity, relevant findings, chosen personal notes, citations, and references. Generated content and personal commentary remain distinguishable.

**E2. Comparison data.** CSV export preserves paper identity, comparison dimensions, values, qualifications, and source references. The export agrees with the visible result and handles ordinary punctuation, long text, and missing values correctly.

**E3. Bibliography.** Users can export BibTeX references for papers used in a project or comparison. Unknown metadata is omitted or identified for review; author lists, publication details, and identifiers are never fabricated.

**E4. Honest handoff.** Exports retain warnings that materially affect interpretation. They identify the evidence set and creation date. Local links are identified as local workspace links, while public source links and full paper references remain useful outside the application.

An export is a working research artifact for the user to review and develop. The product must not imply that a generated brief is a publication-ready literature review.

## 10. Progress, waiting, and control

These are required parts of every long operation, including discovery, paper analysis, chat, comparison, and research synthesis.

**W1. A visible current activity.** The product names what is happening in understandable terms: finding papers, downloading a paper, reading its content, preparing notes, finding supporting passages, or writing the brief.

**W2. Elapsed time.** Users can see elapsed time for the overall active run and current activity. Paper collections show how many papers are complete, waiting, active, or need attention. Returning to the workspace shows actual elapsed time rather than restarting the clock visually.

**W3. Honest expectations.** Queueing and active processing look different. Estimated remaining time is shown only when supported by observed work, and is labelled approximate. The product must not invent progress percentages, promise a fixed completion time, or make a stalled operation look continuously productive.

**W4. Distinguish the outcomes.** Users can immediately distinguish:

| User-visible state | Meaning | What the user can do |
| --- | --- | --- |
| Waiting | Work is saved and has not started | Leave and return, or stop remaining work |
| In progress | A named activity is running | Read available papers and watch progress |
| Recovering | Interrupted work is being resumed | See what is restarting and retain completed results |
| Needs attention | A named item prevents completion | Retry it or explicitly exclude it |
| Complete with limitations | Useful output is available, with stated restrictions | Inspect the affected sections and retry if useful |
| Complete | The requested supported work finished | Inspect, annotate, compare, and export |
| Failed | The operation ended without the requested result | Read the reason and retry without losing prior work |
| Stopped | The user's stop request has taken effect | Keep completed results and resume deliberately |

**W5. Warnings explain consequences.** A warning states what failed, which paper or section is affected, whether the workflow continues, and what can be done. Internal validation messages and raw exceptions are available for troubleshooting rather than being the primary product explanation.

Example: "AI notes could not be completed for Paper B. Source excerpts are available. The other three papers are ready, and the brief will use this limited result unless you retry it."

**W6. Slow work is visible.** When an operation takes longer than its expected range, the product identifies the active activity and offers an appropriate wait, stop, or retry action. A user should not need the terminal to determine whether work ended, is still active, or is waiting for recovery.

**W7. Stop and retry safely.** Users can stop remaining project or comparison work without deleting finished papers or outputs. If an active activity cannot stop immediately, the interface says "Stopping" until the stop takes effect. Retry targets affected work; repeated clicks do not create confusing duplicate runs.

## 11. Evidence quality and partial results

**T1. Verifiable provenance.** Every factual generated finding or answer about a paper is connected to an available source passage. Citations identify the correct paper and page and provide a faithful excerpt. A plausible-looking citation is insufficient if it does not support the claim.

**T2. Definitions are visible.** The interface uses plain explanations for:

- AI summary: a generated explanation based on the selected evidence.
- Source excerpt: words taken directly from a paper, possibly shortened and clearly identified as such.
- Researcher note: the user's own commentary.
- Suggested experiment: a proposed next investigation, not an existing reported result.

**T3. Preserve valid parts.** A citation formatting issue should be corrected when its source is unambiguous. Unresolved or unsupported sections are repaired or marked unavailable. Useful validated sections are retained wherever possible. No claim becomes acceptable merely by removing its citation.

**T4. Source excerpts are a separate experience.** When an AI summary cannot be produced, the reader shows "AI summary unavailable" and a clearly labelled source-excerpt area. Arbitrary early passages must not be placed under headings such as Results or Limitations and presented as successful summaries.

**T5. Partial briefs are explicit.** If synthesis is unavailable, an evidence packet can still list the available papers and relevant extracts. It is labelled as an evidence packet, not a completed answer. It does not invent consensus, conflicts, experiments, or research directions.

**T6. Limited retrieval is disclosed.** If the system found no relevant passage, it says so. Displaying a passage from the beginning of a paper does not by itself establish relevance to the user's question.

**T7. Previous work remains useful.** A failed replacement preserves the last successful summary, brief, or comparison, together with a clear indication of which question and evidence set it answers. The user is never told an outdated result is a newly completed one.

**T8. Demonstration and legacy results are identifiable.** Demonstration content is clearly labelled. Results whose provenance or generation history cannot be established are marked as needing review rather than silently presented as newly verified work.

Citation checks provide source traceability. Human evaluation must also establish that the cited passage actually supports the generated interpretation. Both are part of product quality.

## 12. Overall experience, access, and data expectations

**U1. Consistent navigation.** Research, Reader, Compare, Library, and saved projects are easy to find. The same paper has a consistent identity and opens in the same reader from every entry point. Normal tasks never require hidden debug screens.

**U2. Reading comfort.** Typography, controls, spacing, citations, warnings, and forms are consistent. PDFs stay readable, comparison areas scroll intentionally, and ordinary pages fit their viewport. Long titles, abstracts, errors, and author lists do not break the layout.

**U3. Accessible interaction.** Main tasks work with a keyboard, focus is visible, controls have meaningful names, contrast is readable, and reduced-motion preferences are respected. Verify ordinary laptop sizes and narrow mobile screens, including populated and error states.

**U4. Preserve user intent.** Forms keep useful input after an error. Changing papers or projects does not mix their content. Navigation, refresh, and repeated actions do not erase saved work or unexpectedly start duplicate work.

**U5. Understand data handling.** Users can understand which paper content or questions may be sent to an external AI service and which artifacts remain in their workspace. Running the application on a personal computer must not be presented as a guarantee that all processing is offline.

**U6. Research materials remain usable.** Users can identify their saved papers and exported artifacts, understand removal actions, and follow documented instructions to preserve or restore their workspace. Personal annotations must not disappear during ordinary updates or reanalysis.

## 13. Acceptance scenarios

These scenarios define observable success. They are repeated with real papers as features are built and defects are fixed. Passing automated tests alone does not establish that generated research content is useful or accurate.

| Scenario | Required observable result |
| --- | --- |
| A clear question with four relevant papers | Reviewable recommendations, four approved papers, understandable progress, a saved cited brief, and an explanation of evidence limits |
| An ambiguous acronym such as JEV | The intended meaning is clarified or explicitly bounded before a confident conclusion is presented |
| A query without suitable arXiv evidence | An honest insufficient-evidence outcome with useful refinement options |
| The known 18-page paper | Notes account for methods, evaluation, results, and limitations from the body; citations support their sections and open the correct pages |
| Ask about an unreported experiment | The answer states that the available paper evidence does not establish it, without inventing a result |
| Ask a follow-up, then reopen the paper | The conversation, reading position, and personal notes are preserved |
| One faulty citation among otherwise useful sections | The citation is repaired or the affected section is unavailable; unrelated validated content remains usable |
| AI generation unavailable | Clearly labelled excerpts or a partial evidence packet, an actionable warning, and no fabricated synthesis |
| One failed paper among four approved papers | The failed item and its effect are visible; successful work survives; retry or explicit exclusion leads to an understandable outcome |
| Different datasets with apparently conflicting scores | The comparison explains incompatible conditions and avoids an unsupported winner |
| Reanalysis or evidence-set changes | Previous useful output stays readable, personal notes survive, and outdated output is identified until replacement succeeds |
| Refresh, navigate away, then reopen a running project | The same saved project and true progress are restored without duplicate work |
| Interrupt the application during synthesis | Reopening identifies recovery and leads to a completed result or a clear actionable failure |
| A long-running operation | Current activity, elapsed time, queue state, slow-operation notice, and applicable controls are visible without terminal inspection |
| Export a completed project | The artifact agrees with the displayed result, retains references and material limitations, and preserves selected personal commentary |
| Use a narrow screen, long titles, and keyboard navigation | Core tasks remain readable and operable without accidental page-wide overflow |

For each test, record the question or paper, expected outcome, observed result, elapsed time, affected saved item, and supporting screenshot or error detail. Timing observations distinguish the total wait from individual activities and exclude the user's approval time.

The earlier 4–6 minute estimate for a four-paper research workflow is a provisional expectation to measure on the configured environment, not an established guarantee. The product must remain understandable and recoverable when work is slower. Performance claims in the portfolio must come from recorded tests.

## 14. Definition of the complete portfolio product

ResearchMacha is ready to call complete when:

1. A new user can set it up, understand its supported scope, and perform a real research task using the normal interface.
2. A question can lead to reviewed sources, inspectable findings, saved research context, and an exportable brief.
3. The reader helps users understand the main body of a paper, verify evidence, ask grounded follow-ups, and preserve their own annotations.
4. Comparison produces useful differences and limitations with traceable evidence, rather than a table of generic summaries.
5. Projects, conversations, personal notes, comparisons, and completed outputs can be reopened and continued.
6. Partial results, warnings, slow work, failed items, retries, exclusions, stopping, and recovery have clear user-facing behavior.
7. The acceptance scenarios pass on a representative set of real papers and research questions, including adverse cases. No known defect that loses user work, assigns evidence to the wrong paper, or blocks a core workflow remains unresolved.
8. Repeated end-to-end use is successful enough to demonstrate without relying on preselected happy paths. Recorded limitations are explicit and match the actual experience.
9. The interface is consistent across the complete workflows, including empty, loading, populated, partial, and error states.
10. Setup instructions, capabilities, limitations, troubleshooting, screenshots, and the project explanation reflect the finished behavior. A fellow researcher can follow them without developer assistance.

The final portfolio demonstration should show an ordinary research question, a justified evidence selection, one checked source passage, a meaningful cross-paper comparison, a personal annotation, a saved/reopened workspace, and an exported artifact. Recovery behavior should be demonstrable as part of normal product quality.

## 15. How this specification guides ongoing work

- Build and test against the user outcomes above. Each implementation change should identify the requirement it improves and the scenario that demonstrates it.
- Fix defects discovered during real use as part of that work. Research content quality is reviewed alongside interaction and reliability.
- Add agreed product ideas to this document before treating them as part of the completion scope. This keeps the intended product explicit and finite.
- Keep current capability documentation honest about requirements that remain unfinished. This target specification does not serve as evidence that a feature already works.
- Use this document for what the product should do. Keep implementation choices and architecture explanations in separate documents.
