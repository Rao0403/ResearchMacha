import type { Citation } from "../types";
import { CitationChip } from "./ui";

type ResearchCitation = Citation & { paper_id?: string | null; title?: string | null };

export function ResearchCitationLink({ citation }: { citation: ResearchCitation }) {
  return (
    <CitationChip
      citation={citation}
      paperId={citation.paper_id}
      paperTitle={citation.title}
      detailed
    />
  );
}
