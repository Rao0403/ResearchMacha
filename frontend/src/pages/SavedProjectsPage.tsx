import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Alert, EmptyState, PageHeader, StatusBadge, Surface } from "../components/ui";
import { listSavedProjects, type SavedProject } from "../lib/api";

export function SavedProjectsPage() {
  const [projects, setProjects] = useState<SavedProject[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    listSavedProjects(controller.signal).then((data) => {
      if (!controller.signal.aborted) setProjects(data);
    }).catch((e: unknown) => {
      if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Could not load projects.");
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, []);
  return <div className="research-workspace">
    <PageHeader eyebrow="Saved work" title="Research projects" description="Return to your questions, evidence, and findings." actions={<Link className="ui-button ui-button-primary" to="/">New research</Link>} />
    {error && <Alert tone="danger" title="Projects unavailable"><p>{error}</p></Alert>}
    {loading && <p role="status">Loading projects...</p>}
    {!loading && !error && !projects.length && <EmptyState title="No saved projects yet" description="Start with a research question. Your work will appear here." />}
    {projects.map((project) => <Surface key={project.id}>
      <StatusBadge status={project.status} />
      <h2><Link to={`/projects/${project.id}`}>{project.name || project.question}</Link></h2>
      {project.name && <p>{project.question}</p>}
      <p>{project.paper_count} papers · Updated {new Date(project.updated_at).toLocaleDateString()}</p>
    </Surface>)}
  </div>;
}
