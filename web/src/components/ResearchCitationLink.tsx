import { Link } from "react-router-dom";

import type { Citation } from "../types";

type ResearchCitation = Citation & { paper_id?: string | null; title?: string | null };

export function ResearchCitationLink({ citation }: { citation: ResearchCitation }) {
  const content = (
    <>
      <span>
        <strong>{citation.title ?? "Source paper"}</strong>
        <em>Page {citation.page}</em>
      </span>
      <q>{citation.excerpt}</q>
    </>
  );

  if (!citation.paper_id) {
    return <span className="provenance-citation">{content}</span>;
  }

  return (
    <Link
      className="provenance-citation provenance-citation-link"
      to={`/reader/${citation.paper_id}?page=${citation.page}`}
      title={`Open ${citation.title ?? "source paper"} on page ${citation.page}`}
    >
      {content}
    </Link>
  );
}
