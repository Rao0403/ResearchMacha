import { useEffect, useState } from "react";
import { listPapers } from "../lib/api";
import type { LibraryPaper } from "../types";
import { ActionButton, StatusBadge } from "./ui";

export function LibraryPaperPicker({ selected, onChange, exclude = [], maximum = 10, disabled = false }: {
  selected: string[]; onChange: (ids: string[]) => void; exclude?: string[]; maximum?: number; disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [papers, setPapers] = useState<LibraryPaper[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setLoading(true); setError("");
    listPapers(controller.signal).then((data) => { if (!controller.signal.aborted) setPapers(data); })
      .catch((e: unknown) => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Library unavailable"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [open]);
  const available = papers.filter((p) => !exclude.includes(p.id) && ["ready", "degraded"].includes(p.status))
    .filter((p) => `${p.title} ${p.authors.join(" ")}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  return <section className="library-picker" aria-label="Choose library evidence">
    <ActionButton type="button" variant="secondary" onClick={() => setOpen(!open)} aria-expanded={open} disabled={disabled}>
      {open ? "Hide library" : "Choose from library"}
    </ActionButton>
    {selected.length > 0 && <p role="status">{selected.length} library papers selected. Existing analyses will be reused.</p>}
    {open && <>
      <label>Search library<input type="search" value={query} onChange={(e) => setQuery(e.target.value)} /></label>
      <p>Ready and degraded papers can be reused without another analysis charge.</p>
      {loading && <p role="status">Loading library...</p>}
      {error && <p role="alert">{error}</p>}
      {!loading && !error && available.length === 0 && <p>No reusable papers match. Upload a PDF in the reader or wait for processing to finish.</p>}
      <div className="library-picker-list">{available.map((paper) => <label className="library-picker-row" key={paper.id}>
        <input type="checkbox" checked={selected.includes(paper.id)} disabled={disabled || (!selected.includes(paper.id) && selected.length >= maximum)}
          onChange={(e) => onChange(e.target.checked ? [...selected, paper.id] : selected.filter((id) => id !== paper.id))} />
        <span>{paper.title}<small>{paper.authors.join(", ") || "Unknown authors"}</small></span>
        <StatusBadge status={paper.status} />
      </label>)}</div>
    </>}
  </section>;
}
