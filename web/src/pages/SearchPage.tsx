import { FormEvent, startTransition, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { importArxivPaper, listPapers, searchPapers, uploadPaper } from "../lib/api";
import type { LibraryPaper, PaperSearchResult, UploadPaperResponse } from "../types";

export function SearchPage() {
  const [query, setQuery] = useState("retrieval augmented generation");
  const [results, setResults] = useState<PaperSearchResult[]>([]);
  const [recentPapers, setRecentPapers] = useState<LibraryPaper[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    void loadRecentPapers();
  }, []);

  async function loadRecentPapers() {
    try {
      const papers = await listPapers();
      setRecentPapers(papers.slice(0, 5));
    } catch {
      setRecentPapers([]);
    }
  }

  async function handleSearch(event?: FormEvent) {
    event?.preventDefault();
    if (!query.trim()) {
      return;
    }
    setLoading(true);
    setMessage(null);
    try {
      const data = await searchPapers(query.trim());
      startTransition(() => {
        setResults(data);
      });
    } catch (error) {
      setMessage(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }

  async function handleImport(arxivId: string) {
    setMessage("Importing paper and starting analysis...");
    try {
      const response = await importArxivPaper(arxivId);
      setMessage(buildImportMessage(response));
      await loadRecentPapers();
    } catch (error) {
      setMessage(getErrorMessage(error));
    }
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    const file = formData.get("file");
    if (!(file instanceof File) || file.size === 0) {
      setMessage("Choose a PDF before uploading.");
      return;
    }

    setUploading(true);
    setMessage("Uploading PDF and starting analysis...");
    try {
      const response = await uploadPaper(formData);
      setMessage(buildImportMessage(response));
      form.reset();
      await loadRecentPapers();
    } catch (error) {
      setMessage(getErrorMessage(error));
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="page-content">
      <section className="hero-card">
        <div className="hero-copy">
          <p className="eyebrow">V1 research workflow</p>
          <h2>Find papers, import them fast, and read them with evidence attached.</h2>
          <p>
            Search arXiv, save papers into your library, then open a paper workspace built around structured notes,
            grounded highlights, and cited chat.
          </p>
        </div>
        <div className="hero-metrics">
          <div>
            <strong>{recentPapers.length}</strong>
            <span>recent library items</span>
          </div>
          <div>
            <strong>6</strong>
            <span>summary sections per paper</span>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="section-header">
          <div>
            <p className="eyebrow">Discover</p>
            <h3>Search arXiv</h3>
          </div>
        </div>
        <form className="search-form" onSubmit={handleSearch}>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search a problem, method, or keyword"
          />
          <button type="submit" disabled={loading}>
            {loading ? "Searching..." : "Search"}
          </button>
        </form>
        {message ? <p className="status-note">{message}</p> : null}
        <div className="results-grid">
          {results.map((result) => (
            <article className="result-card" key={result.arxiv_id}>
              <div className="result-meta">
                <span>{result.year ?? "Unknown year"}</span>
                <span>{result.arxiv_id}</span>
              </div>
              <h4>{result.title}</h4>
              <p className="authors">{result.authors.join(", ")}</p>
              <p className="abstract-preview">{result.abstract}</p>
              <div className="card-actions">
                <button type="button" onClick={() => handleImport(result.arxiv_id)}>
                  Import & analyze
                </button>
                <a href={result.entry_url} target="_blank" rel="noreferrer">
                  Open arXiv
                </a>
              </div>
            </article>
          ))}
          {!loading && results.length === 0 ? (
            <div className="empty-card">
              <p>Search results will appear here.</p>
            </div>
          ) : null}
        </div>
      </section>

      <section className="two-column-grid">
        <div className="panel">
          <div className="section-header">
            <div>
              <p className="eyebrow">Import</p>
              <h3>Upload a PDF</h3>
            </div>
          </div>
          <form className="upload-form" onSubmit={handleUpload}>
            <label>
              Title
              <input name="title" placeholder="Optional paper title" />
            </label>
            <label>
              Authors
              <input name="authors" placeholder="Comma-separated authors" />
            </label>
            <label>
              PDF file
              <input name="file" type="file" accept="application/pdf" />
            </label>
            <button type="submit" disabled={uploading}>
              {uploading ? "Uploading..." : "Upload & analyze"}
            </button>
          </form>
        </div>

        <div className="panel">
          <div className="section-header">
            <div>
              <p className="eyebrow">Library</p>
              <h3>Recent papers</h3>
            </div>
            <Link to="/library" className="text-link">
              View all
            </Link>
          </div>
          <div className="mini-library">
            {recentPapers.map((paper) => (
              <Link to={`/papers/${paper.id}`} className="mini-library-card" key={paper.id}>
                <span className={`status-pill status-${paper.status}`}>{paper.status}</span>
                <strong>{paper.title}</strong>
                <p>{paper.authors.join(", ") || "Unknown authors"}</p>
              </Link>
            ))}
            {recentPapers.length === 0 ? <p className="status-note">Your library is still empty.</p> : null}
          </div>
        </div>
      </section>
    </div>
  );
}

function buildImportMessage(response: UploadPaperResponse) {
  return `Imported "${response.paper.title}" and queued analysis job ${response.job.id}.`;
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong.";
}
