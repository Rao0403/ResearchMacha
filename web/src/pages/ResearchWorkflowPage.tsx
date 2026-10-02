import { FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { GenerationNotice } from "../components/GenerationNotice";
import { ResearchCitationLink } from "../components/ResearchCitationLink";
import { ActionButton, Alert, Field, PageHeader, StatusBadge, Surface } from "../components/ui";
import { useSingleFlightPolling } from "../hooks/useSingleFlightPolling";
import {
  approveResearchWorkflow,
  createResearchWorkflow,
  excludeResearchWorkflowCandidate,
  excludeResearchWorkflowPaper,
  getResearchWorkflow,
  getResearchWorkflowStatus,
  retryJob,
} from "../lib/api";
import type {
  AgentRun,
  AgentStep,
  BlockingItem,
  Job,
  ResearchBrief,
  ResearchCandidate,
  ResearchFinding,
  ResearchMemory,
  ResearchProject,
} from "../types";

const workflowSteps = [
  { label: "Discover", description: "Plan and find relevant papers" },
  { label: "Select", description: "Review the recommended evidence" },
  { label: "Analyze", description: "Import and process approved papers" },
  { label: "Synthesize", description: "Build the citation-backed brief" },
];

const briefSections: Array<[keyof ResearchBrief, string]> = [
  ["key_findings", "Key findings"],
  ["evidence_table", "Evidence"],
  ["conflicts_or_gaps", "Conflicts and gaps"],
  ["suggested_experiments", "Suggested experiments"],
  ["suggested_research_directions", "Research directions"],
];

export function ResearchWorkflowPage() {
  const [question, setQuestion] = useState("");
  const [project, setProject] = useState<ResearchProject | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [message, setMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [approving, setApproving] = useState(false);
  const [busyItem, setBusyItem] = useState<string | null>(null);
  const projectRef = useRef(project);
  const projectRevisionRef = useRef(0);
  const actionControllerRef = useRef<AbortController | null>(null);
  projectRef.current = project;

  useEffect(() => {
    return () => {
      projectRevisionRef.current += 1;
      actionControllerRef.current?.abort();
    };
  }, []);

  const pollingEnabled = Boolean(project && ["importing", "analyzing", "synthesis_queued", "synthesizing"].includes(project.status));
  useSingleFlightPolling({
    enabled: pollingEnabled,
    identity: project?.id ?? "no-project",
    intervalMs: 4000,
    poll: async (signal) => {
      if (!project || projectRef.current?.id !== project.id) {
        return;
      }
      try {
        const status = await getResearchWorkflowStatus(project.id, signal);
        const current = projectRef.current;
        if (signal.aborted || current?.id !== status.id) {
          return;
        }
        const changed = status.status !== current.status
          || status.synthesis_generation !== current.synthesis_generation
          || status.updated_at !== current.updated_at;
        if (!changed) {
          return;
        }
        const nextProject = await getResearchWorkflow(project.id, signal);
        if (!signal.aborted && projectRef.current?.id === nextProject.id) {
          projectRef.current = nextProject;
          setProject(nextProject);
        }
      } catch (error) {
        if (!isAbortError(error) && projectRef.current?.id === project.id) {
          setMessage(getErrorMessage(error));
        }
      }
    },
  });

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!question.trim()) {
      return;
    }

    projectRevisionRef.current += 1;
    const revision = projectRevisionRef.current;
    actionControllerRef.current?.abort();
    const controller = new AbortController();
    actionControllerRef.current = controller;
    setSubmitting(true);
    setBusyItem(null);
    setMessage(null);
    projectRef.current = null;
    setProject(null);
    setSelected(new Set());
    try {
      const nextProject = await createResearchWorkflow(question.trim(), controller.signal);
      if (controller.signal.aborted || projectRevisionRef.current !== revision) {
        return;
      }
      projectRef.current = nextProject;
      setProject(nextProject);
      setSelected(new Set(nextProject.candidates.filter((candidate) => candidate.selected).map((candidate) => candidate.id)));
    } catch (error) {
      if (!isAbortError(error) && projectRevisionRef.current === revision) {
        setMessage(getErrorMessage(error));
      }
    } finally {
      if (actionControllerRef.current === controller) {
        actionControllerRef.current = null;
        setSubmitting(false);
      }
    }
  }

  async function handleApprove() {
    if (!project || selected.size === 0) {
      return;
    }

    const projectId = project.id;
    const revision = projectRevisionRef.current;
    actionControllerRef.current?.abort();
    const controller = new AbortController();
    actionControllerRef.current = controller;
    setApproving(true);
    setMessage(null);
    try {
      const nextProject = await approveResearchWorkflow(projectId, Array.from(selected), controller.signal);
      if (controller.signal.aborted || projectRevisionRef.current !== revision || projectRef.current?.id !== projectId) {
        return;
      }
      projectRef.current = nextProject;
      setProject(nextProject);
    } catch (error) {
      if (!isAbortError(error) && projectRevisionRef.current === revision && projectRef.current?.id === projectId) {
        setMessage(getErrorMessage(error));
      }
    } finally {
      if (actionControllerRef.current === controller) {
        actionControllerRef.current = null;
        setApproving(false);
      }
    }
  }

  async function handleRetry(jobId: string) {
    if (!project) {
      return;
    }
    const projectId = project.id;
    const revision = projectRevisionRef.current;
    actionControllerRef.current?.abort();
    const controller = new AbortController();
    actionControllerRef.current = controller;
    setBusyItem(`retry:${jobId}`);
    setMessage(null);
    try {
      await retryJob(jobId, controller.signal);
      const nextProject = await getResearchWorkflow(projectId, controller.signal);
      if (controller.signal.aborted || projectRevisionRef.current !== revision || projectRef.current?.id !== projectId) {
        return;
      }
      projectRef.current = nextProject;
      setProject(nextProject);
    } catch (error) {
      if (!isAbortError(error) && projectRevisionRef.current === revision && projectRef.current?.id === projectId) {
        setMessage(getErrorMessage(error));
      }
    } finally {
      if (actionControllerRef.current === controller) {
        actionControllerRef.current = null;
        setBusyItem(null);
      }
    }
  }

  async function handleExclude(blocker: BlockingItem) {
    if (!project || blocker.target_type === "synthesis") {
      return;
    }
    const projectId = project.id;
    const revision = projectRevisionRef.current;
    actionControllerRef.current?.abort();
    const controller = new AbortController();
    actionControllerRef.current = controller;
    const actionKey = `exclude:${blocker.target_type}:${blocker.target_id}`;
    setBusyItem(actionKey);
    setMessage(null);
    try {
      const nextProject = blocker.target_type === "candidate"
        ? await excludeResearchWorkflowCandidate(projectId, blocker.target_id, controller.signal)
        : await excludeResearchWorkflowPaper(projectId, blocker.target_id, controller.signal);
      if (controller.signal.aborted || projectRevisionRef.current !== revision || projectRef.current?.id !== projectId) {
        return;
      }
      projectRef.current = nextProject;
      setProject(nextProject);
      setSelected((current) => {
        const next = new Set(current);
        next.delete(blocker.target_id);
        return next;
      });
    } catch (error) {
      if (!isAbortError(error) && projectRevisionRef.current === revision && projectRef.current?.id === projectId) {
        setMessage(getErrorMessage(error));
      }
    } finally {
      if (actionControllerRef.current === controller) {
        actionControllerRef.current = null;
        setBusyItem(null);
      }
    }
  }

  function toggleCandidate(candidateId: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(candidateId)) {
        next.delete(candidateId);
      } else {
        next.add(candidateId);
      }
      return next;
    });
  }

  return (
    <div className="research-workspace">
      <PageHeader
        eyebrow="Research workflow"
        title="Ask one research question. Get a cited evidence brief."
        description="Discover relevant papers, choose the evidence, and follow every synthesized claim back to its source."
      />

      <Surface className="research-question-panel">
        <form className="research-question-form" onSubmit={handleSubmit}>
          <Field label="Research question" htmlFor="research-question" hint="Be specific about the domain, method, population, or outcome you want to investigate.">
            <textarea
              id="research-question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Example: What are reliable methods for reducing hallucinations in retrieval augmented generation systems?"
              rows={4}
            />
          </Field>
          <ActionButton type="submit" busy={submitting} busyLabel="Finding papers...">Start research</ActionButton>
        </form>
      </Surface>

      <WorkflowProgress status={project?.status} busy={submitting} />
      {message ? <Alert tone="danger" title="The workflow could not continue" role="alert"><p>{message}</p></Alert> : null}
      {submitting ? <AgentLoadingState /> : null}
      {project ? <WorkflowStats project={project} selectedCount={selected.size} /> : null}

      {project && (project.agent_run || project.memory_signals?.length) ? (
        <details className="research-technical-details">
          <summary>
            <span>Technical details</span>
            <small>Tool execution and reusable memory signals</small>
          </summary>
          <div className="research-technical-content">
            {project.agent_run ? <AgentTrace run={project.agent_run} /> : null}
            {project.memory_signals?.length ? <MemorySignals memories={project.memory_signals} /> : null}
          </div>
        </details>
      ) : null}

      {project?.blocking_items.length ? (
        <WorkflowBlockers
          blockers={project.blocking_items}
          busyItem={busyItem}
          onExclude={handleExclude}
          onRetry={handleRetry}
        />
      ) : null}

      {project?.recent_jobs.some((job) => job.warning_message || job.status === "completed_with_warnings") ? (
        <JobWarnings jobs={project.recent_jobs} busyItem={busyItem} onRetry={handleRetry} />
      ) : null}

      {project ? (
        <Surface className="candidate-panel">
          <div className="research-section-heading">
            <div>
              <p className="research-section-kicker">Evidence selection</p>
              <h3>Recommended papers</h3>
              <p>Review relevance and remove weak matches before any PDFs are imported.</p>
            </div>
            <StatusBadge status={project.status} />
          </div>

          <CandidateCards candidates={project.candidates} selected={selected} onToggle={toggleCandidate} />

          {project.status === "no_candidates" ? (
            <p className="status-note">
              No arXiv candidates were found for this question. Try a more specific question with concrete methods,
              datasets, or keywords.
            </p>
          ) : null}

          {project.status === "awaiting_approval" && project.candidates.length > 0 ? (
            <div className="approval-row">
              <p>{selected.size} papers selected. You can unselect weak matches before continuing.</p>
              <ActionButton
                type="button"
                onClick={() => void handleApprove()}
                disabled={selected.size === 0}
                busy={approving}
                busyLabel="Starting analysis..."
              >Approve selected papers</ActionButton>
            </div>
          ) : null}
        </Surface>
      ) : null}

      {project?.papers.length ? (
        <Surface className="imported-panel">
          <div className="research-section-heading">
            <div>
              <p className="research-section-kicker">Analysis</p>
              <h3>Imported papers</h3>
            </div>
          </div>
          <div className="research-paper-list">
            {project.papers.map((paper) => (
              <Link to={`/reader/${paper.id}`} className="paper-status-row" key={paper.id}>
                <span>{paper.title}</span>
                <StatusBadge status={paper.status} />
              </Link>
            ))}
          </div>
        </Surface>
      ) : null}

      {project?.synthesis_json ? (
        <Surface className="brief-panel">
          <div className="research-section-heading">
            <div>
              <p className="research-section-kicker">Final brief</p>
              <h3>Cited findings and next directions</h3>
              <p>Generated claims are separated from the exact evidence used to support them.</p>
            </div>
          </div>
          <ResearchBriefView brief={project.synthesis_json} />
        </Surface>
      ) : null}
    </div>
  );
}

function WorkflowBlockers({
  blockers,
  busyItem,
  onExclude,
  onRetry,
}: {
  blockers: BlockingItem[];
  busyItem: string | null;
  onExclude: (blocker: BlockingItem) => Promise<void>;
  onRetry: (jobId: string) => Promise<void>;
}) {
  return (
    <Surface className="blocker-panel" aria-labelledby="workflow-blockers-title">
      <div className="research-section-heading">
        <div>
          <p className="research-section-kicker">Action required</p>
          <h3 id="workflow-blockers-title">Resolve failed work before synthesis</h3>
          <p>Retry the failed step or exclude that source from this project.</p>
        </div>
        <StatusBadge status="blocked" label={`${blockers.length} blocked`} />
      </div>
      <div className="blocker-list">
        {blockers.map((blocker) => {
          const excludeKey = `exclude:${blocker.target_type}:${blocker.target_id}`;
          return (
            <article className="blocker-card" key={`${blocker.target_type}:${blocker.target_id}:${blocker.job_id ?? "none"}`}>
              <div>
                <span>{blocker.target_type}</span>
                <strong>{blocker.title}</strong>
                <p>{blocker.error ?? "This item failed and is preventing synthesis."}</p>
              </div>
              <div className="blocker-actions">
                {blocker.job_id ? (
                  <ActionButton
                    type="button"
                    size="compact"
                    onClick={() => void onRetry(blocker.job_id!)}
                    busy={busyItem === `retry:${blocker.job_id}`}
                    busyLabel="Retrying..."
                    disabled={busyItem !== null && busyItem !== `retry:${blocker.job_id}`}
                  >
                    Retry
                  </ActionButton>
                ) : null}
                {blocker.target_type !== "synthesis" ? (
                  <ActionButton
                    type="button"
                    variant="secondary"
                    size="compact"
                    onClick={() => void onExclude(blocker)}
                    busy={busyItem === excludeKey}
                    busyLabel="Excluding..."
                    disabled={busyItem !== null && busyItem !== excludeKey}
                  >
                    Exclude
                  </ActionButton>
                ) : null}
              </div>
            </article>
          );
        })}
      </div>
    </Surface>
  );
}

function JobWarnings({ jobs, busyItem, onRetry }: { jobs: Job[]; busyItem: string | null; onRetry: (jobId: string) => Promise<void> }) {
  const warningJobs = jobs.filter((job) => job.warning_message || job.status === "completed_with_warnings");
  return (
    <Surface className="job-warning-panel">
      <div className="research-section-heading">
        <div>
          <p className="research-section-kicker">Workflow notices</p>
          <h3>Job warnings and recovery</h3>
        </div>
      </div>
      <div className="job-warning-list">
        {warningJobs.map((job) => (
          <article key={job.id}>
            <div>
              <strong>{job.job_type.replace(/_/g, " ")}</strong>
              <p>{job.warning_message ?? "This job completed with warnings."}</p>
            </div>
            {job.status === "completed_with_warnings" ? (
              <ActionButton
                type="button"
                variant="secondary"
                size="compact"
                onClick={() => void onRetry(job.id)}
                busy={busyItem === `retry:${job.id}`}
                busyLabel="Retrying..."
                disabled={busyItem !== null && busyItem !== `retry:${job.id}`}
              >Retry</ActionButton>
            ) : null}
          </article>
        ))}
      </div>
    </Surface>
  );
}

function AgentLoadingState() {
  return (
    <Surface className="loading-workbench" aria-live="polite">
      <div>
        <p className="research-section-kicker">Discovering evidence</p>
        <h3>Planning searches and reviewing arXiv candidates...</h3>
      </div>
      <div className="loading-steps" aria-label="Research workflow loading steps">
        <span>Plan search</span>
        <span>Find papers</span>
        <span>Rank evidence</span>
        <span>Select shortlist</span>
      </div>
    </Surface>
  );
}

function WorkflowStats({ project, selectedCount }: { project: ResearchProject; selectedCount: number }) {
  const readyPapers = project.papers.filter((paper) => paper.status === "ready").length;
  const failedPapers = project.papers.filter((paper) => paper.status === "failed").length;
  return (
    <section className="workflow-stats" aria-label="Research workflow snapshot">
      <span>
        <strong>{project.candidates.length}</strong>
        candidates
      </span>
      <span>
        <strong>{selectedCount}</strong>
        selected
      </span>
      <span>
        <strong>{project.papers.length}</strong>
        imported
      </span>
      <span>
        <strong>{readyPapers}</strong>
        ready
      </span>
      <span>
        <strong>{failedPapers}</strong>
        failed
      </span>
      <span>
        <strong>{project.memory_signals?.length ?? 0}</strong>
        memory signals
      </span>
    </section>
  );
}

function AgentTrace({ run }: { run: AgentRun }) {
  return (
    <section className="technical-panel agent-trace-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Agent trace</p>
          <h3>Tool execution timeline</h3>
        </div>
        <StatusBadge status={run.status} />
      </div>
      <div className="agent-trace">
        {run.steps.map((step) => (
          <article className={`trace-step trace-${step.status}`} key={step.id}>
            <span className="trace-dot" />
            <div>
              <strong>{toolLabel(step.tool_name)}</strong>
              <p>{stepSummary(step)}</p>
              {memoryStepSummary(step) ? <p className="memory-note">{memoryStepSummary(step)}</p> : null}
              {fallbackSummary(step) ? <p className="fallback-note">{fallbackSummary(step)}</p> : null}
            </div>
            <StatusBadge status={step.status} />
          </article>
        ))}
      </div>
    </section>
  );
}

function MemorySignals({ memories }: { memories: ResearchMemory[] }) {
  return (
    <section className="technical-panel memory-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Memory signals</p>
          <h3>What this workflow can reuse</h3>
        </div>
      </div>
      <div className="memory-list">
        {memories.map((memory) => (
          <article className="memory-row" key={memory.id}>
            <div>
              <span className="memory-meta">
                {memory.scope} / {memory.memory_type} / importance {memory.importance}
              </span>
              <p>{memory.text}</p>
            </div>
            <span className="status-pill">{memory.source}</span>
          </article>
        ))}
      </div>
    </section>
  );
}

function toolLabel(toolName: string) {
  const labels: Record<string, string> = {
    plan_search: "Plan search",
    search_arxiv: "Search arXiv",
    rank_candidates: "Rank candidates",
    select_candidates: "Select candidates",
    import_papers: "Import papers",
    analyze_papers: "Analyze papers",
    synthesize_brief: "Synthesize brief",
  };
  return labels[toolName] ?? toolName.replace(/_/g, " ");
}

function stepSummary(step: AgentStep) {
  if (step.status === "failed") {
    return step.error_message ?? "Step failed.";
  }
  const output = step.output_json ?? {};
  if (step.tool_name === "plan_search") {
    return `${countArray(output.search_queries)} search queries, ${countArray(output.inclusion_criteria)} criteria`;
  }
  if (step.tool_name === "search_arxiv") {
    return `${numberValue(output.unique_candidate_count)} unique candidates from arXiv`;
  }
  if (step.tool_name === "rank_candidates") {
    return `${numberValue(output.candidate_count)} candidates ranked by relevance`;
  }
  if (step.tool_name === "select_candidates") {
    return `${numberValue(output.selected_count)} papers selected for approval${memoryCountSuffix(output)}`;
  }
  if (step.tool_name === "import_papers") {
    return `${countArray(output.imported_papers)} PDFs imported`;
  }
  if (step.tool_name === "analyze_papers") {
    return `${countArray(output.queued_jobs)} analysis jobs queued`;
  }
  if (step.tool_name === "synthesize_brief") {
    return `${numberValue(output.key_findings)} findings, ${numberValue(output.suggested_experiments)} experiment ideas${memoryCountSuffix(output)}`;
  }
  return step.status === "running" ? "Running..." : "Completed.";
}

function memoryStepSummary(step: AgentStep) {
  const output = step.output_json ?? {};
  const input = step.input_json ?? {};
  const memoryCount = numberValue(output.memory_count ?? input.memory_count);
  if (!memoryCount) {
    return null;
  }
  const adjusted = output.memory_adjusted_candidates;
  if (Array.isArray(adjusted) && adjusted.length > 0) {
    return `Memory used: ${memoryCount} signals, adjusted ${adjusted.length} candidate scores.`;
  }
  return `Memory checked: ${memoryCount} signals.`;
}

function memoryCountSuffix(output: Record<string, unknown>) {
  const memoryCount = numberValue(output.memory_count);
  return memoryCount ? ` using ${memoryCount} memory signals` : "";
}

function fallbackSummary(step: AgentStep) {
  const fallbacks = step.output_json?.fallbacks;
  if (!Array.isArray(fallbacks) || fallbacks.length === 0) {
    return null;
  }
  const first = fallbacks[0] as { component?: string; fallback?: string; reason?: string };
  const extraCount = fallbacks.length > 1 ? ` + ${fallbacks.length - 1} more` : "";
  return `Fallback used: ${first.component ?? "primary"} -> ${first.fallback ?? "fallback"}${extraCount}. ${first.reason ?? ""}`;
}

function countArray(value: unknown) {
  return Array.isArray(value) ? value.length : 0;
}

function numberValue(value: unknown) {
  return typeof value === "number" ? value : 0;
}

function WorkflowProgress({ status, busy }: { status?: string; busy: boolean }) {
  const currentIndex = getWorkflowStepIndex(status, busy);
  return (
    <ol className="research-progress" aria-label="Research workflow progress">
      {workflowSteps.map((step, index) => (
        <li className={index < currentIndex ? "done" : index === currentIndex ? "current" : ""} key={step.label}>
          <span className="research-progress-index" aria-hidden="true">{index + 1}</span>
          <span>
            <strong>{step.label}</strong>
            <small>{step.description}</small>
          </span>
        </li>
      ))}
    </ol>
  );
}

function getWorkflowStepIndex(status: string | undefined, busy: boolean) {
  if (busy) {
    return 0;
  }
  if (!status) {
    return 0;
  }
  if (status === "awaiting_approval") {
    return 1;
  }
  if (status === "no_candidates") {
    return 0;
  }
  if (["importing", "analyzing", "blocked"].includes(status)) {
    return 2;
  }
  if (["synthesis_queued", "synthesizing"].includes(status)) {
    return 3;
  }
  if (["done", "degraded"].includes(status)) {
    return 4;
  }
  return 0;
}

function CandidateCards({
  candidates,
  selected,
  onToggle,
}: {
  candidates: ResearchCandidate[];
  selected: Set<string>;
  onToggle: (candidateId: string) => void;
}) {
  if (!candidates.length) {
    return <p className="status-note">No candidates found yet.</p>;
  }

  return (
    <div className="candidate-card-list">
      {candidates.map((candidate) => {
        const isSelected = selected.has(candidate.id);
        return (
          <article className={`candidate-card${isSelected ? " candidate-card-selected" : ""}`} key={candidate.id}>
            <label className="candidate-card-select">
              <input
                type="checkbox"
                checked={isSelected}
                onChange={() => onToggle(candidate.id)}
                aria-label={`Select ${candidate.title}`}
              />
              <span aria-hidden="true">{isSelected ? "Selected" : "Select paper"}</span>
            </label>
            <div className="candidate-card-content">
              <div className="candidate-card-heading">
                <div>
                  <h4>{candidate.title}</h4>
                  <p>{candidate.authors.join(", ") || "Unknown authors"}{candidate.year ? ` · ${candidate.year}` : ""}</p>
                </div>
                <ScoreMeter score={candidate.score} />
              </div>
              <p className="candidate-rationale">{candidate.rationale}</p>
              <p className="candidate-abstract">{candidate.abstract}</p>
              <a href={candidate.entry_url} target="_blank" rel="noreferrer">View arXiv record</a>
            </div>
          </article>
        );
      })}
    </div>
  );
}

function ScoreMeter({ score }: { score: number }) {
  return (
    <div className="score-meter" aria-label={`Candidate score ${score}`}>
      <strong>{score}</strong>
      <span>
        <i style={{ width: `${Math.max(4, Math.min(100, score))}%` }} />
      </span>
    </div>
  );
}

function ResearchBriefView({ brief }: { brief: ResearchBrief }) {
  return (
    <div className="research-brief">
      <GenerationNotice mode={brief.generation_mode} warnings={brief.warnings} />
      <div className="research-brief-executive">
        <span>Executive synthesis</span>
        <p>{brief.executive_summary}</p>
      </div>
      <div className="research-brief-sections">
        {briefSections.map(([key, label]) => (
          <section className="research-brief-section" key={key}>
            <header>
              <h4>{label}</h4>
              <span>{(brief[key] as ResearchFinding[]).length}</span>
            </header>
            {(brief[key] as ResearchFinding[]).length ? (brief[key] as ResearchFinding[]).map((finding, index) => (
              <article className="research-finding" key={`${key}-${finding.label}-${index}`}>
                <strong>{finding.label}</strong>
                <p>{finding.summary}</p>
                <div className="research-finding-evidence">
                  <span>Supporting evidence</span>
                  <div className="citation-row">
                    {finding.citations.map((citation, citationIndex) => (
                      <ResearchCitationLink citation={citation} key={`${key}-${index}-${citationIndex}`} />
                    ))}
                  </div>
                </div>
              </article>
            )) : <p className="research-empty-section">No supported findings were generated for this section.</p>}
          </section>
        ))}
      </div>
    </div>
  );
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong.";
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
