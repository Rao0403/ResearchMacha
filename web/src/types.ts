export interface Citation {
  page: number;
  excerpt: string;
  chunk_id?: string | null;
}

export interface PaperSearchResult {
  arxiv_id: string;
  title: string;
  authors: string[];
  abstract: string;
  year?: number | null;
  pdf_url: string;
  entry_url: string;
}

export interface LibraryPaper {
  id: string;
  source: string;
  title: string;
  authors: string[];
  abstract?: string | null;
  year?: number | null;
  arxiv_id?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  last_opened_at?: string | null;
}

export interface PaperChunk {
  id: string;
  chunk_index: number;
  page_start: number;
  page_end: number;
  section_label?: string | null;
  text: string;
}

export interface Highlight {
  id: string;
  position: number;
  label: string;
  explanation: string;
  citations: Citation[];
}

export interface PaperSummary {
  problem_or_hypothesis: string;
  approach: string;
  experiments: string;
  results: string;
  conclusion: string;
  limitations_or_notes: string;
  section_citations: Record<string, Citation[]>;
}

export interface PaperDetail extends LibraryPaper {
  chunks: PaperChunk[];
  summary?: PaperSummary | null;
  highlights: Highlight[];
}

export interface PaperSummaryResponse {
  paper: PaperDetail;
  summary: PaperSummary;
  highlights: Highlight[];
}

export interface Job {
  id: string;
  paper_id: string;
  job_type: string;
  status: string;
  error_message?: string | null;
  payload?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface UploadPaperResponse {
  paper: LibraryPaper;
  job: Job;
}

export interface BatchUploadResponse {
  items: UploadPaperResponse[];
}

export interface BatchPaperSummary {
  paper_id: string;
  title: string;
  main_idea: string;
  problem_or_hypothesis: string;
  experiments: string;
  models_and_datasets: string;
  results: string;
  conclusions: string;
}

export interface BatchSummaryResponse {
  overall_takeaway: string;
  papers: BatchPaperSummary[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  created_at: string;
}

export interface ChatResponse {
  session_id: string;
  answer: ChatMessage;
  citations: Citation[];
  retrieved_chunk_ids: string[];
}

export interface ResearchCandidate {
  id: string;
  project_id: string;
  arxiv_id: string;
  title: string;
  authors: string[];
  abstract: string;
  year?: number | null;
  pdf_url: string;
  entry_url: string;
  score: number;
  rationale: string;
  selected: boolean;
  created_at: string;
}

export interface ResearchFinding {
  label: string;
  summary: string;
  citations: Array<Citation & { paper_id?: string | null; title?: string | null }>;
}

export interface ResearchBrief {
  executive_summary: string;
  key_findings: ResearchFinding[];
  evidence_table: ResearchFinding[];
  conflicts_or_gaps: ResearchFinding[];
  suggested_experiments: ResearchFinding[];
  suggested_research_directions: ResearchFinding[];
}

export interface ResearchProject {
  id: string;
  question: string;
  status: string;
  generated_queries: string[];
  inclusion_criteria: string[];
  synthesis_json?: ResearchBrief | null;
  created_at: string;
  updated_at: string;
  candidates: ResearchCandidate[];
  papers: LibraryPaper[];
}
