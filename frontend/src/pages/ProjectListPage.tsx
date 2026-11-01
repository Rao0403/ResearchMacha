import { FlaskConical, Play, Plus, RefreshCw } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { createDemoProject, createResearchProject, listResearchProjects } from "../lib/api";
import type { ResearchProject } from "../types";

export function ProjectListPage() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ResearchProject[]>([]);
  const [question, setQuestion] = useState("How can retrieval augmented generation improve factuality in domain-specific question answering?");
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void loadProjects();
  }, []);

  async function loadProjects() {
    try {
      setProjects(await listResearchProjects());
      setStatus(null);
    } catch (error) {
      setStatus(getErrorMessage(error));
    }
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    if (!question.trim()) {
      return;
    }
    setBusy(true);
    try {
      const project = await createResearchProject(question.trim());
      navigate(`/projects/${project.id}`);
    } catch (error) {
      setStatus(getErrorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function handleDemo() {
    setBusy(true);
    try {
      const project = await createDemoProject();
      navigate(`/projects/${project.id}`);
    } catch (error) {
      setStatus(getErrorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page-content">
      <section className="workbench-header">
        <div>
          <p className="eyebrow">ResearchMacha</p>
          <h2>Research question to cited brief</h2>
          <p className="lede">Create a project, discover arXiv papers, import evidence, then synthesize findings and next experiments.</p>
        </div>
        <button type="button" className="icon-button" onClick={() => void loadProjects()} aria-label="Refresh projects">
          <RefreshCw size={18} />
        </button>
      </section>

      {status ? <p className="status-note">{status}</p> : null}

      <section className="tool-surface">
        <form className="question-form" onSubmit={handleCreate}>
          <label>
            Research question
            <textarea value={question} onChange={(event) => setQuestion(event.target.value)} rows={4} />
          </label>
          <div className="button-row">
            <button type="submit" disabled={busy}>
              <Plus size={18} />
              Create project
            </button>
            <button type="button" className="secondary-button" onClick={() => void handleDemo()} disabled={busy}>
              <Play size={18} />
              Load demo
            </button>
          </div>
        </form>
      </section>

      <section className="project-grid">
        {projects.map((project) => (
          <Link to={`/projects/${project.id}`} className="project-card" key={project.id}>
            <div className="project-card-topline">
              <span className={`status-pill status-${project.status}`}>{project.status}</span>
              <FlaskConical size={18} />
            </div>
            <h3>{project.question}</h3>
            <p>{project.papers.length} papers, {project.candidates.length} candidates</p>
          </Link>
        ))}
        {projects.length === 0 ? (
          <div className="empty-card">
            <p>No research projects yet.</p>
          </div>
        ) : null}
      </section>
    </div>
  );
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong.";
}
