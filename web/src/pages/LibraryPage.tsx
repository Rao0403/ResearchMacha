import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { listPapers } from "../lib/api";
import type { LibraryPaper } from "../types";

export function LibraryPage() {
  const [papers, setPapers] = useState<LibraryPaper[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void load();
  }, []);

  async function load() {
    try {
      setPapers(await listPapers());
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load library.");
    }
  }

  return (
    <div className="page-content">
      <section className="panel">
        <div className="section-header">
          <div>
            <p className="eyebrow">Library</p>
            <h2>Saved papers</h2>
          </div>
          <button type="button" onClick={() => void load()}>
            Refresh
          </button>
        </div>

        {error ? <p className="status-note">{error}</p> : null}

        <div className="library-grid">
          {papers.map((paper) => (
            <Link to={`/papers/${paper.id}`} className="library-card" key={paper.id}>
              <div className="result-meta">
                <span className={`status-pill status-${paper.status}`}>{paper.status}</span>
                <span>{paper.year ?? "No year"}</span>
              </div>
              <h3>{paper.title}</h3>
              <p className="authors">{paper.authors.join(", ") || "Unknown authors"}</p>
              <p className="abstract-preview">
                {paper.abstract || "Uploaded PDF without an abstract. Open the workspace to read the extracted notes."}
              </p>
            </Link>
          ))}
          {papers.length === 0 ? (
            <div className="empty-card">
              <p>Import a paper from the Discover screen to start building your library.</p>
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}

