import type { Citation } from "../../types";
import { Link } from "react-router-dom";

interface CitationChipProps {
  citation: Citation;
  paperId?: string | null;
  paperTitle?: string | null;
  detailed?: boolean;
}

export function CitationChip({ citation, paperId, paperTitle, detailed = false }: CitationChipProps) {
  const label = paperTitle ? `${paperTitle}, page ${citation.page}` : `Page ${citation.page}`;
  const className = detailed ? "provenance-citation provenance-citation-link" : "ui-citation-chip";
  const content = detailed ? (
    <>
      <span><strong>{paperTitle ?? "Source paper"}</strong><em>Page {citation.page}</em></span>
      <q>{citation.excerpt}</q>
    </>
  ) : <span>{label}</span>;

  if (!paperId) {
    return <span className={detailed ? "provenance-citation" : className} title={citation.excerpt}>{content}</span>;
  }

  return (
    <Link
      className={className}
      to={`/reader/${paperId}?page=${citation.page}`}
      title={`Open ${paperTitle ?? "source paper"} on page ${citation.page}`}
      aria-label={`Open ${label}: ${citation.excerpt}`}
    >
      {content}
    </Link>
  );
}
