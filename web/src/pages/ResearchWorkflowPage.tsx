import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { approveResearchWorkflow, createResearchWorkflow, getResearchWorkflow } from "../lib/api";
import type { ResearchBrief, ResearchCandidate, ResearchFinding, ResearchProject } from "../types";

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

          {project.status === "awaiting_approval" ? (
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
