import { BookOpen, Check, FileDown, FlaskConical, Lightbulb, RefreshCw, Search, Sparkles } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  discoverResearchCandidates,
  getResearchProject,
  importSelectedCandidates,
  planResearchProject,
  synthesizeResearchProject,
} from "../lib/api";
import type { ResearchBrief, ResearchCandidate, ResearchFinding, ResearchProject } from "../types";

const briefSections: Array<[keyof ResearchBrief, string]> = [
  ["key_findings", "Key findings"],
  ["evidence_table", "Evidence table"],
  ["conflicts_or_gaps", "Conflicts and gaps"],
  ["suggested_experiments", "Suggested experiments"],
  ["suggested_research_directions", "Research directions"],
];

export function ProjectWorkspacePage() {
  const { projectId = "" } = useParams();
  const [project, setProject] = useState<ResearchProject | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [message, setMessage] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);

  useEffect(() => {
    void loadProject();
  }, [projectId]);

  async function loadProject() {
    try {
      const nextProject = await getResearchProject(projectId);
      setProject(nextProject);
      setSelected(new Set(nextProject.candidates.filter((candidate) => candidate.selected).map((candidate) => candidate.id)));
      setMessage(null);
    } catch (error) {
      setMessage(getErrorMessage(error));
    }
  }

  async function runAction(actionName: string, action: () => Promise<ResearchProject | unknown>) {
    setBusyAction(actionName);
    try {
      const result = await action();
      if (result && typeof result === "object" && "id" in result) {
        setProject(result as ResearchProject);
      } else {
        await loadProject();
      }
      setMessage(null);
    } catch (error) {
      setMessage(getErrorMessage(error));
    } finally {
      setBusyAction(null);
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

  if (!project) {
    return (
      <div className="page-content">
        <p className="status-note">{message ?? "Loading project..."}</p>
      </div>
    );
  }

  return (
    <div className="page-content">
      <section className="workbench-header">
        <div>
          <p className="eyebrow">Project workspace</p>
          <h2>{project.question}</h2>
          <p className="lede">A deterministic agentic RAG flow: plan, discover, read, synthesize.</p>
        </div>
        <div className="button-row">
          <span className={`status-pill status-${project.status}`}>{project.status}</span>
          <button type="button" className="icon-button" onClick={() => void loadProject()} aria-label="Refresh project">
            <RefreshCw size={18} />
          </button>
        </div>
      </section>

      {message ? <p className="status-note">{message}</p> : null}

      <section className="stage-grid">
        <StageCard icon={<Sparkles size={18} />} title="Plan" active={Boolean(project.generated_queries.length)}>
          <div className="button-row">
            <button type="button" disabled={busyAction === "plan"} onClick={() => void runAction("plan", () => planResearchProject(project.id))}>
              <Sparkles size={17} />
              Generate plan
            </button>
          </div>
          <TagList label="Queries" items={project.generated_queries} />
          <TagList label="Criteria" items={project.inclusion_criteria} />
        </StageCard>

        <StageCard icon={<Search size={18} />} title="Discover" active={Boolean(project.candidates.length)}>
          <button type="button" disabled={busyAction === "discover"} onClick={() => void runAction("discover", () => discoverResearchCandidates(project.id))}>
            <Search size={17} />
            Search arXiv
          </button>
          <p className="muted-line">{project.candidates.length} ranked candidates</p>
        </StageCard>

        <StageCard icon={<FileDown size={18} />} title="Read" active={Boolean(project.papers.length)}>
          <button
            type="button"
            disabled={busyAction === "import" || selected.size === 0}
            onClick={() => void runAction("import", () => importSelectedCandidates(project.id, Array.from(selected)))}
          >
            <FileDown size={17} />
            Import selected
          </button>
          <p className="muted-line">{project.papers.length} imported papers</p>
        </StageCard>

        <StageCard icon={<Lightbulb size={18} />} title="Synthesize" active={Boolean(project.synthesis_json)}>
          <button type="button" disabled={busyAction === "synthesize"} onClick={() => void runAction("synthesize", () => synthesizeResearchProject(project.id))}>
            <Lightbulb size={17} />
            Generate brief
          </button>
          <p className="muted-line">Strictly cited findings and directions</p>
        </StageCard>
      </section>

      <section className="split-workbench">
        <div className="tool-surface">
          <div className="section-header">
            <div>
              <p className="eyebrow">Discover</p>
              <h3>Ranked arXiv candidates</h3>
            </div>
          </div>
          <div className="candidate-list">
            {project.candidates.map((candidate) => (
              <CandidateRow
                candidate={candidate}
                selected={selected.has(candidate.id)}
                onToggle={() => toggleCandidate(candidate.id)}
                key={candidate.id}
              />
            ))}
            {project.candidates.length === 0 ? <p className="status-note">Run discovery to populate candidate papers.</p> : null}
          </div>
        </div>

        <div className="tool-surface">
          <div className="section-header">
            <div>
              <p className="eyebrow">Collection</p>
              <h3>Imported papers</h3>
            </div>
          </div>
          <div className="paper-link-list">
            {project.papers.map((paper) => (
              <Link to={`/papers/${paper.id}`} className="paper-link-row" key={paper.id}>
                <BookOpen size={17} />
                <span>{paper.title}</span>
                <span className={`status-pill status-${paper.status}`}>{paper.status}</span>
              </Link>
            ))}
            {project.papers.length === 0 ? <p className="status-note">Imported papers will appear here.</p> : null}
          </div>
        </div>
      </section>

      <section className="tool-surface">
        <div className="section-header">
          <div>
            <p className="eyebrow">Synthesis</p>
            <h3>Cited research brief</h3>
          </div>
          <FlaskConical size={20} />
        </div>
        {project.synthesis_json ? <ResearchBriefView brief={project.synthesis_json} /> : <p className="status-note">Run synthesis after importing and analyzing papers.</p>}
      </section>
    </div>
  );
}

function StageCard({ icon, title, active, children }: { icon: ReactNode; title: string; active: boolean; children: ReactNode }) {
  return (
    <article className={`stage-card${active ? " stage-card-active" : ""}`}>
      <div className="stage-title">
        {icon}
        <h3>{title}</h3>
        {active ? <Check size={17} /> : null}
      </div>
      {children}
    </article>
  );
}

function TagList({ label, items }: { label: string; items: string[] }) {
  if (!items.length) {
    return null;
  }
  return (
    <div className="tag-list">
      <span>{label}</span>
      {items.map((item) => (
        <em key={item}>{item}</em>
      ))}
    </div>
  );
}

function CandidateRow({ candidate, selected, onToggle }: { candidate: ResearchCandidate; selected: boolean; onToggle: () => void }) {
  return (
    <article className="candidate-row">
      <label className="candidate-selector">
        <input type="checkbox" checked={selected} onChange={onToggle} />
        <span>{selected ? "Selected" : "Select"}</span>
      </label>
      <div>
        <div className="candidate-title-line">
          <h4>{candidate.title}</h4>
          <span className="score-badge">{candidate.score}</span>
        </div>
        <p className="authors">{candidate.authors.join(", ") || "Unknown authors"} {candidate.year ? `(${candidate.year})` : ""}</p>
        <p className="abstract-preview">{candidate.abstract}</p>
        <p className="muted-line">{candidate.rationale}</p>
      </div>
    </article>
  );
}

function ResearchBriefView({ brief }: { brief: ResearchBrief }) {
  return (
    <div className="brief-layout">
      <p className="brief-summary">{brief.executive_summary}</p>
      {briefSections.map(([key, label]) => (
        <div className="brief-section" key={key}>
          <h4>{label}</h4>
          {(brief[key] as ResearchFinding[]).map((finding, index) => (
            <article className="finding-row" key={`${key}-${finding.label}-${index}`}>
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
        </div>
      ))}
    </div>
  );
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong.";
}
