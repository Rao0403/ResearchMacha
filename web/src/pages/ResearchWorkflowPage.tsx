import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { approveResearchWorkflow, createResearchWorkflow, getResearchWorkflow } from "../lib/api";
import type { AgentRun, AgentStep, ResearchBrief, ResearchCandidate, ResearchFinding, ResearchMemory, ResearchProject } from "../types";

const workflowSteps = ["Planning", "Finding papers", "Awaiting approval", "Analyzing", "Synthesizing", "Done"];

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

  useEffect(() => {
    if (!project || !["importing", "analyzing", "synthesizing"].includes(project.status)) {
      return;
    }

    const interval = window.setInterval(async () => {
      try {
        const nextProject = await getResearchWorkflow(project.id);
        setProject(nextProject);
      } catch (error) {
        setMessage(getErrorMessage(error));
      }
    }, 4000);

    return () => window.clearInterval(interval);
  }, [project]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!question.trim()) {
      return;
    }

    setSubmitting(true);
    setMessage(null);
    setProject(null);
    setSelected(new Set());
    try {
      const nextProject = await createResearchWorkflow(question.trim());
      setProject(nextProject);
      setSelected(new Set(nextProject.candidates.filter((candidate) => candidate.selected).map((candidate) => candidate.id)));
    } catch (error) {
      setMessage(getErrorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleApprove() {
    if (!project || selected.size === 0) {
      return;
    }

    setApproving(true);
    setMessage(null);
    try {
      const nextProject = await approveResearchWorkflow(project.id, Array.from(selected));
      setProject(nextProject);
    } catch (error) {
      setMessage(getErrorMessage(error));
    } finally {
      setApproving(false);
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
    <div className="mvp-page">
      <section className="mvp-header">
        <p className="eyebrow">Research workflow</p>
        <h2>Ask one research question. Approve the papers. Get a cited brief.</h2>
      </section>

      <form className="research-command" onSubmit={handleSubmit}>
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Example: What are reliable methods for reducing hallucinations in retrieval augmented generation systems?"
          rows={3}
        />
        <button type="submit" disabled={submitting}>
          {submitting ? "Planning and finding papers..." : "Start"}
        </button>
      </form>

      <StatusTrack status={project?.status} busy={submitting} />
      {message ? <p className="status-note">{message}</p> : null}

      {project?.agent_run ? <AgentTrace run={project.agent_run} /> : null}
      {project?.memory_signals?.length ? <MemorySignals memories={project.memory_signals} /> : null}

      {project ? (
        <section className="mvp-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Selected by agent</p>
              <h3>Recommended papers</h3>
            </div>
            <span className={`status-pill status-${project.status}`}>{project.status}</span>
          </div>

          <CandidateTable candidates={project.candidates} selected={selected} onToggle={toggleCandidate} />

          {project.status === "no_candidates" ? (
            <p className="status-note">
              No arXiv candidates were found for this question. Try a more specific question with concrete methods,
              datasets, or keywords.
            </p>
          ) : null}

          {project.status === "awaiting_approval" && project.candidates.length > 0 ? (
            <div className="approval-row">
              <p>{selected.size} papers selected. You can unselect weak matches before continuing.</p>
              <button type="button" onClick={() => void handleApprove()} disabled={approving || selected.size === 0}>
                {approving ? "Importing and analyzing..." : "Approve selected papers"}
              </button>
            </div>
          ) : null}
        </section>
      ) : null}

      {project?.papers.length ? (
        <section className="mvp-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Analysis progress</p>
              <h3>Imported papers</h3>
            </div>
          </div>
          <div className="simple-list">
            {project.papers.map((paper) => (
              <Link to={`/reader/${paper.id}`} className="paper-status-row" key={paper.id}>
                <span>{paper.title}</span>
                <span className={`status-pill status-${paper.status}`}>{paper.status}</span>
              </Link>
            ))}
          </div>
        </section>
      ) : null}

      {project?.synthesis_json ? (
        <section className="mvp-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Final brief</p>
              <h3>Cited findings and next directions</h3>
            </div>
          </div>
          <ResearchBriefView brief={project.synthesis_json} />
        </section>
      ) : null}
    </div>
  );
}

function AgentTrace({ run }: { run: AgentRun }) {
  return (
    <section className="mvp-panel agent-trace-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Agent trace</p>
          <h3>Tool execution timeline</h3>
        </div>
        <span className={`status-pill status-${run.status}`}>{run.status}</span>
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
            <span className={`status-pill status-${step.status}`}>{step.status}</span>
          </article>
        ))}
      </div>
    </section>
  );
}

function MemorySignals({ memories }: { memories: ResearchMemory[] }) {
  return (
    <section className="mvp-panel memory-panel">
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

function StatusTrack({ status, busy }: { status?: string; busy: boolean }) {
  const currentIndex = getStepIndex(status, busy);
  return (
    <ol className="status-track">
      {workflowSteps.map((step, index) => (
        <li className={index < currentIndex ? "done" : index === currentIndex ? "current" : ""} key={step}>
          {step}
        </li>
      ))}
    </ol>
  );
}

function getStepIndex(status: string | undefined, busy: boolean) {
  if (busy) {
    return 1;
  }
  if (!status) {
    return 0;
  }
  if (status === "awaiting_approval") {
    return 2;
  }
  if (status === "no_candidates") {
    return 1;
  }
  if (["importing", "analyzing"].includes(status)) {
    return 3;
  }
  if (status === "synthesizing") {
    return 4;
  }
  if (status === "done") {
    return 5;
  }
  return 1;
}

function CandidateTable({
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
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>Select</th>
            <th>Paper</th>
            <th>Year</th>
            <th>Score</th>
            <th>Rationale</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((candidate) => (
            <tr key={candidate.id}>
              <td>
                <input type="checkbox" checked={selected.has(candidate.id)} onChange={() => onToggle(candidate.id)} />
              </td>
              <td>
                <strong>{candidate.title}</strong>
                <span>{candidate.authors.join(", ") || "Unknown authors"}</span>
              </td>
              <td>{candidate.year ?? "n/a"}</td>
              <td>{candidate.score}</td>
              <td>{candidate.rationale}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResearchBriefView({ brief }: { brief: ResearchBrief }) {
  return (
    <div className="brief-layout">
      <p className="brief-summary">{brief.executive_summary}</p>
      {briefSections.map(([key, label]) => (
        <section className="brief-section" key={key}>
          <h4>{label}</h4>
          {(brief[key] as ResearchFinding[]).map((finding, index) => (
            <article className="finding-row compact" key={`${key}-${finding.label}-${index}`}>
              <strong>{finding.label}</strong>
              <p>{finding.summary}</p>
              <div className="citation-row">
                {finding.citations.map((citation, citationIndex) => (
                  <span className="citation-chip" key={`${key}-${index}-${citationIndex}`}>
                    p.{citation.page}
                  </span>
                ))}
              </div>
            </article>
          ))}
        </section>
      ))}
    </div>
  );
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong.";
}
