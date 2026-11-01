import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { ActionButton, Alert, EmptyState, PageHeader, Skeleton, StatusBadge, Surface } from "../components/ui";
import { listPapers } from "../lib/api";
import type { LibraryPaper } from "../types";

const dateFormatter = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });

export function LibraryPage() {
  const [papers, setPapers] = useState<LibraryPaper[]>([]);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestRef = useRef<AbortController | null>(null);

  useEffect(() => {
    void load();
    return () => requestRef.current?.abort();
  }, []);

  const availableStatuses = useMemo(
    () => Array.from(new Set(papers.map((paper) => paper.status))).sort(),
    [papers],
  );
  const filteredPapers = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    return [...papers]
      .filter((paper) => statusFilter === "all" || paper.status === statusFilter)
      .filter((paper) => {
        if (!normalizedQuery) return true;
        return [paper.title, paper.abstract ?? "", paper.authors.join(" ")]
          .some((value) => value.toLocaleLowerCase().includes(normalizedQuery));
      })
      .sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at));
  }, [papers, query, statusFilter]);

  async function load() {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    try {
      const result = await listPapers(controller.signal);
      if (controller.signal.aborted) return;
      setPapers(result);
      setError(null);
    } catch (loadError) {
      if (!controller.signal.aborted) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load library.");
      }
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null;
        setLoading(false);
      }
    }
  }

  function clearFilters() {
    setQuery("");
    setStatusFilter("all");
  }

  return (
    <div className="library-workspace">
      <PageHeader
        eyebrow="Library"
        title="Your paper collection"
        description="Return to saved papers, inspect analysis state, and continue reading from one focused workspace."
        actions={(
          <ActionButton type="button" variant="secondary" onClick={() => void load()} busy={loading} busyLabel="Refreshing...">
            Refresh
          </ActionButton>
        )}
      />

      <Surface className="library-toolbar" aria-label="Filter saved papers">
        <label className="library-search">
          <span>Search papers</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Title, author, or abstract"
          />
        </label>
        <label className="library-filter">
          <span>Analysis status</span>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="all">All statuses</option>
            {availableStatuses.map((status) => (
              <option value={status} key={status}>{formatStatus(status)}</option>
            ))}
          </select>
        </label>
        <p className="library-result-count" aria-live="polite">
          <strong>{filteredPapers.length}</strong> of {papers.length} papers
        </p>
      </Surface>

      {error ? (
        <Alert tone="danger" title="Library unavailable" role="alert">
          <p>{error}</p>
          <ActionButton type="button" variant="secondary" size="compact" onClick={() => void load()}>Try again</ActionButton>
        </Alert>
      ) : null}

      {loading && papers.length === 0 ? <LibrarySkeleton /> : null}

      {!loading && !error && papers.length === 0 ? (
        <Surface>
          <EmptyState
            title="Your library is empty"
            description="Upload a PDF in the reader to create cited notes, highlights, and grounded chat in this collection."
            actions={<Link className="ui-button ui-button-primary" to="/reader">Upload your first paper</Link>}
          />
        </Surface>
      ) : null}

      {!loading && papers.length > 0 && filteredPapers.length === 0 ? (
        <Surface>
          <EmptyState
            title="No papers match these filters"
            description="Try a different title or author, or return to all analysis states."
            actions={<ActionButton type="button" variant="secondary" onClick={clearFilters}>Clear filters</ActionButton>}
          />
        </Surface>
      ) : null}

      {filteredPapers.length > 0 ? (
        <Surface className="library-list-surface">
          <div className="library-list-heading">
            <div>
              <p>Saved evidence</p>
              <h2>Recently updated</h2>
            </div>
            <span>Open a paper to continue reading, review notes, or ask a question.</span>
          </div>
          <div className="library-list" role="list">
            {filteredPapers.map((paper) => <LibraryRow paper={paper} key={paper.id} />)}
          </div>
        </Surface>
      ) : null}
    </div>
  );
}

function LibraryRow({ paper }: { paper: LibraryPaper }) {
  const metadata = [paper.year, paper.source === "upload" ? "Uploaded PDF" : paper.source].filter(Boolean).join(" · ");
  return (
    <article className="library-row" role="listitem">
      <div className="library-row-main">
        <div className="library-row-title">
          <Link to={`/reader/${paper.id}`}>{paper.title}</Link>
          <StatusBadge status={paper.status} />
        </div>
        <p className="library-row-authors">{paper.authors.join(", ") || "Unknown authors"}</p>
        <p className="library-row-abstract">
          {paper.abstract || "No abstract is stored for this PDF. Open the reader to inspect its extracted notes."}
        </p>
        {paper.analysis_warning ? <p className="library-row-warning">{paper.analysis_warning}</p> : null}
      </div>
      <div className="library-row-side">
        <span>{metadata || "Saved paper"}</span>
        <span>Updated {formatDate(paper.updated_at)}</span>
        <Link className="library-open-link" to={`/reader/${paper.id}`}>Open reader</Link>
      </div>
    </article>
  );
}

function LibrarySkeleton() {
  return (
    <Surface className="library-list-surface" aria-label="Loading saved papers">
      {[0, 1, 2].map((item) => (
        <div className="library-skeleton-row" key={item}>
          <Skeleton width="42%" height="1.15rem" label={item === 0 ? "Loading saved papers" : "Loading"} />
          <Skeleton width="28%" height="0.8rem" />
          <Skeleton width="76%" height="0.8rem" />
        </div>
      ))}
    </Surface>
  );
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "recently" : dateFormatter.format(date);
}

function formatStatus(status: string) {
  return status.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}
