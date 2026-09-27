import type {
  BatchSummaryResponse,
  BatchUploadResponse,
  ChatResponse,
  Job,
  LibraryPaper,
  PaperDetail,
  PaperSearchResult,
  PaperStatus,
  PaperSummaryResponse,
  ResearchBrief,
  ResearchProject,
  UploadPaperResponse,
} from "../types";

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000/api";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, init);
  if (!response.ok) {
    throw await responseError(response);
  }
  return (await response.json()) as T;
}

async function responseError(response: Response): Promise<ApiError> {
  const text = await response.text();
  let payload: unknown = text;
  if (text) {
    try {
      payload = JSON.parse(text) as unknown;
    } catch {
      payload = text;
    }
  }
  const detail = isRecord(payload) && "detail" in payload ? payload.detail : payload;
  if (typeof detail === "string" && detail) {
    return new ApiError(detail, response.status, undefined, detail);
  }
  if (isRecord(detail)) {
    const message = typeof detail.message === "string" ? detail.message : `Request failed with status ${response.status}`;
    const code = typeof detail.code === "string" ? detail.code : undefined;
    return new ApiError(message, response.status, code, detail);
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (isRecord(item) && typeof item.msg === "string" ? item.msg : null))
      .filter((item): item is string => Boolean(item));
    return new ApiError(messages.join("; ") || `Request failed with status ${response.status}`, response.status, undefined, detail);
  }
  return new ApiError(text || `Request failed with status ${response.status}`, response.status, undefined, detail);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export async function searchPapers(query: string, signal?: AbortSignal): Promise<PaperSearchResult[]> {
  return request<PaperSearchResult[]>(`/papers/search?q=${encodeURIComponent(query)}`, { signal });
}

export async function importArxivPaper(arxivId: string, signal?: AbortSignal): Promise<UploadPaperResponse> {
  return request<UploadPaperResponse>("/papers/import/arxiv", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ arxiv_id: arxivId }),
    signal,
  });
}

export async function uploadPaper(formData: FormData, signal?: AbortSignal): Promise<UploadPaperResponse> {
  return request<UploadPaperResponse>("/papers/upload", {
    method: "POST",
    body: formData,
    signal,
  });
}

export async function batchUploadPapers(formData: FormData, signal?: AbortSignal): Promise<BatchUploadResponse> {
  return request<BatchUploadResponse>("/papers/batch-upload", {
    method: "POST",
    body: formData,
    signal,
  });
}

export async function createBatchSummary(paperIds: string[], goal: string, signal?: AbortSignal): Promise<BatchSummaryResponse> {
  return request<BatchSummaryResponse>("/papers/batch-summary", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paper_ids: paperIds, goal }),
    signal,
  });
}

export async function listPapers(signal?: AbortSignal): Promise<LibraryPaper[]> {
  return request<LibraryPaper[]>("/papers", { signal });
}

export async function getPaper(paperId: string, signal?: AbortSignal): Promise<PaperDetail> {
  return request<PaperDetail>(`/papers/${paperId}`, { signal });
}

export async function getPaperStatus(paperId: string, signal?: AbortSignal): Promise<PaperStatus> {
  return request<PaperStatus>(`/papers/${paperId}/status`, { signal });
}

export async function analyzePaper(paperId: string, signal?: AbortSignal): Promise<Job> {
  return request<Job>(`/papers/${paperId}/analyze`, { method: "POST", signal });
}

export async function getPaperSummary(paperId: string, signal?: AbortSignal): Promise<PaperSummaryResponse> {
  return request<PaperSummaryResponse>(`/papers/${paperId}/summary`, { signal });
}

export async function sendChatMessage(
  paperId: string,
  question: string,
  sessionId?: string,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  return request<ChatResponse>(`/papers/${paperId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, session_id: sessionId ?? null }),
    signal,
  });
}

export function getPdfUrl(paperId: string): string {
  return `${apiBaseUrl}/papers/${paperId}/file`;
}

export async function createResearchProject(question: string, signal?: AbortSignal): Promise<ResearchProject> {
  return request<ResearchProject>("/research-projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
    signal,
  });
}

export async function createResearchWorkflow(question: string, signal?: AbortSignal): Promise<ResearchProject> {
  return request<ResearchProject>("/research-workflows", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
    signal,
  });
}

export async function approveResearchWorkflow(projectId: string, candidateIds: string[], signal?: AbortSignal): Promise<ResearchProject> {
  return request<ResearchProject>(`/research-workflows/${projectId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ candidate_ids: candidateIds }),
    signal,
  });
}

export async function getResearchWorkflow(projectId: string, signal?: AbortSignal): Promise<ResearchProject> {
  return request<ResearchProject>(`/research-workflows/${projectId}`, { signal });
}

export async function createDemoProject(signal?: AbortSignal): Promise<ResearchProject> {
  return request<ResearchProject>("/research-projects/demo", { method: "POST", signal });
}

export async function listResearchProjects(signal?: AbortSignal): Promise<ResearchProject[]> {
  return request<ResearchProject[]>("/research-projects", { signal });
}

export async function getResearchProject(projectId: string, signal?: AbortSignal): Promise<ResearchProject> {
  return request<ResearchProject>(`/research-projects/${projectId}`, { signal });
}

export async function planResearchProject(projectId: string, signal?: AbortSignal): Promise<{ search_queries: string[]; inclusion_criteria: string[] }> {
  return request<{ search_queries: string[]; inclusion_criteria: string[] }>(`/research-projects/${projectId}/plan`, {
    method: "POST",
    signal,
  });
}

export async function discoverResearchCandidates(projectId: string, signal?: AbortSignal): Promise<ResearchProject> {
  return request<ResearchProject>(`/research-projects/${projectId}/discover`, { method: "POST", signal });
}

export async function importSelectedCandidates(projectId: string, candidateIds: string[], signal?: AbortSignal): Promise<ResearchProject> {
  return request<ResearchProject>(`/research-projects/${projectId}/import-selected`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ candidate_ids: candidateIds }),
    signal,
  });
}

export async function synthesizeResearchProject(projectId: string, signal?: AbortSignal): Promise<ResearchProject> {
  return request<ResearchProject>(`/research-projects/${projectId}/synthesize`, { method: "POST", signal });
}

export async function getResearchBrief(projectId: string, signal?: AbortSignal): Promise<ResearchBrief> {
  return request<ResearchBrief>(`/research-projects/${projectId}/brief`, { signal });
}
