import type {
  ChatResponse,
  Job,
  LibraryPaper,
  PaperDetail,
  PaperSearchResult,
  PaperSummaryResponse,
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
