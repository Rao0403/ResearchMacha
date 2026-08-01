import type {
  BatchSummaryResponse,
  BatchUploadResponse,
  ChatResponse,
  Job,
  LibraryPaper,
  PaperDetail,
  PaperSearchResult,
  PaperSummaryResponse,
  ResearchBrief,
  ResearchProject,
  UploadPaperResponse,
} from "../types";

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, init);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function searchPapers(query: string): Promise<PaperSearchResult[]> {
  return request<PaperSearchResult[]>(`/papers/search?q=${encodeURIComponent(query)}`);
}

export async function importArxivPaper(arxivId: string): Promise<UploadPaperResponse> {
  return request<UploadPaperResponse>("/papers/import/arxiv", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ arxiv_id: arxivId }),
  });
}

export async function uploadPaper(formData: FormData): Promise<UploadPaperResponse> {
  return request<UploadPaperResponse>("/papers/upload", {
    method: "POST",
    body: formData,
  });
}

export async function batchUploadPapers(formData: FormData): Promise<BatchUploadResponse> {
  return request<BatchUploadResponse>("/papers/batch-upload", {
    method: "POST",
    body: formData,
  });
}

export async function createBatchSummary(paperIds: string[], goal: string): Promise<BatchSummaryResponse> {
  return request<BatchSummaryResponse>("/papers/batch-summary", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paper_ids: paperIds, goal }),
  });
}

export async function listPapers(): Promise<LibraryPaper[]> {
  return request<LibraryPaper[]>("/papers");
}

export async function getPaper(paperId: string): Promise<PaperDetail> {
  return request<PaperDetail>(`/papers/${paperId}`);
}

export async function analyzePaper(paperId: string): Promise<Job> {
  return request<Job>(`/papers/${paperId}/analyze`, { method: "POST" });
}

export async function getPaperSummary(paperId: string): Promise<PaperSummaryResponse> {
  return request<PaperSummaryResponse>(`/papers/${paperId}/summary`);
}

export async function sendChatMessage(
  paperId: string,
  question: string,
  sessionId?: string,
): Promise<ChatResponse> {
  return request<ChatResponse>(`/papers/${paperId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, session_id: sessionId ?? null }),
  });
}

export function getPdfUrl(paperId: string): string {
  return `${apiBaseUrl}/papers/${paperId}/file`;
}

export async function createResearchProject(question: string): Promise<ResearchProject> {
  return request<ResearchProject>("/research-projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
}

export async function createResearchWorkflow(question: string): Promise<ResearchProject> {
  return request<ResearchProject>("/research-workflows", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
}

export async function approveResearchWorkflow(projectId: string, candidateIds: string[]): Promise<ResearchProject> {
  return request<ResearchProject>(`/research-workflows/${projectId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ candidate_ids: candidateIds }),
  });
}

export async function getResearchWorkflow(projectId: string): Promise<ResearchProject> {
  return request<ResearchProject>(`/research-workflows/${projectId}`);
}

export async function createDemoProject(): Promise<ResearchProject> {
  return request<ResearchProject>("/research-projects/demo", { method: "POST" });
}

export async function listResearchProjects(): Promise<ResearchProject[]> {
  return request<ResearchProject[]>("/research-projects");
}

export async function getResearchProject(projectId: string): Promise<ResearchProject> {
  return request<ResearchProject>(`/research-projects/${projectId}`);
}

export async function planResearchProject(projectId: string): Promise<{ search_queries: string[]; inclusion_criteria: string[] }> {
  return request<{ search_queries: string[]; inclusion_criteria: string[] }>(`/research-projects/${projectId}/plan`, {
    method: "POST",
  });
}

export async function discoverResearchCandidates(projectId: string): Promise<ResearchProject> {
  return request<ResearchProject>(`/research-projects/${projectId}/discover`, { method: "POST" });
}

export async function importSelectedCandidates(projectId: string, candidateIds: string[]): Promise<ResearchProject> {
  return request<ResearchProject>(`/research-projects/${projectId}/import-selected`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ candidate_ids: candidateIds }),
  });
}

export async function synthesizeResearchProject(projectId: string): Promise<ResearchProject> {
  return request<ResearchProject>(`/research-projects/${projectId}/synthesize`, { method: "POST" });
}

export async function getResearchBrief(projectId: string): Promise<ResearchBrief> {
  return request<ResearchBrief>(`/research-projects/${projectId}/brief`);
}
