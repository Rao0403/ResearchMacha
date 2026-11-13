import type { Citation } from "../types";
import { CitationChip } from "./ui";

export function SourcePassage({ citation, onPageClick }: { citation: Citation; onPageClick?: (page: number) => void }) {
  return <div className="source-passage">
    {onPageClick ? <button type="button" className="reader-citation-chip" onClick={() => onPageClick(citation.page)}
      aria-label={`Jump to page ${citation.page}`} title={citation.excerpt}>p.{citation.page}</button>
      : <CitationChip citation={citation} paperId={citation.paper_id} paperTitle={citation.title} />}
    <details><summary>View passage</summary><blockquote>{citation.excerpt}</blockquote></details>
  </div>;
}
