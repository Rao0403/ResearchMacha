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
  ResearchProjectStatus,
  UploadPaperResponse,
  ReaderWorkspace,
  SavedComparison,
  PersonalNote,
} from "../types";

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000/api";

export type ExportKind = "paper" | "research" | "comparison";
export type ExportFormat = "markdown" | "bibtex" | "csv";
export interface ExportOptions {
  has_result: boolean;
  paper_count: number;
  warnings: string[];
  notes: Array<{ id: string; paper_id: string; paper_title: string; page: number | null; preview: string }>;
}
export function getExportOptions(kind: ExportKind, id: string, signal?: AbortSignal) {
  return request<ExportOptions>(`/exports/${kind}/${id}/options`, { signal });
}
export async function downloadSavedWork(kind: ExportKind, id: string, format: ExportFormat, noteIds: string[], signal?: AbortSignal) {
  const query = new URLSearchParams({ format });
  if (format === "markdown") noteIds.forEach((note) => query.append("note_ids", note));
  const response = await fetch(`${apiBaseUrl}/exports/${kind}/${id}?${query}`, { signal });
  if (!response.ok) throw await responseError(response);
  const extension = { markdown: "md", bibtex: "bib", csv: "csv" }[format];
  const filename = response.headers.get("Content-Disposition")?.match(/filename="([^"]+)"/)?.[1]
    ?? `research-macha-${kind}-${id}.${extension}`;
  return { blob: await response.blob(), filename: filename.replace(/[\\/:*?"<>|\u0000-\u001f]/g, "-") };
}

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
  requestId?: string,
  retry = false,
): Promise<ChatResponse> {
  return request<ChatResponse>(`/papers/${paperId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, session_id: sessionId ?? null, request_id: requestId, retry }),
    signal,
  });
}

export function getReaderWorkspace(id: string, signal?: AbortSignal, sessionId?: string) {
  return request<ReaderWorkspace>(`/papers/${id}/workspace${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ""}`, { signal });
}
export function saveReadingState(id: string, page: number, version: number, sessionId: string | undefined, signal?: AbortSignal) {
  return request<{ page: number; version: number }>(`/papers/${id}/reading-state`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ page, version, ...(sessionId ? { active_session_id: sessionId } : {}) }), signal,
  });
}
export function newChatSession(id: string, signal?: AbortSignal) {
  return request<ReaderWorkspace>(`/papers/${id}/chat-sessions`, { method: "POST", signal });
}

export function listPersonalNotes(id: string, signal?: AbortSignal) {
  return request<PersonalNote[]>(`/papers/${id}/notes`, { signal });
}
export function savePersonalNote(paperId: string, note: { id: string; body: string; page: number | null; excerpt: string | null; version?: number }, signal?: AbortSignal) {
  return request<PersonalNote>(`/papers/${paperId}/notes${note.version ? `/${note.id}` : ""}`, {
    method: note.version ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(note), signal,
  });
}
export function deletePersonalNote(paperId: string, note: PersonalNote, signal?: AbortSignal) {
  return request<{ deleted: string }>(`/papers/${paperId}/notes/${note.id}?version=${note.version}`, { method: "DELETE", signal });
}

export function createLibraryResearch(question: string, paperIds: string[], signal?: AbortSignal) {
  return request<ResearchProject>("/research-workflows/from-library", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, paper_ids: paperIds }), signal });
}
export function addProjectPapers(id: string, paperIds: string[], version: number, signal?: AbortSignal) {
  return request<ResearchProject>(`/research-workflows/${id}/papers`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ paper_ids: paperIds, version }), signal });
}
export function generateProjectBrief(id: string, signal?: AbortSignal) {
  return request<ResearchProject>(`/research-workflows/${id}/synthesize`, { method: "POST", signal });
}

export function listComparisons(signal?: AbortSignal) {
  return request<SavedComparison[]>("/comparisons", { signal });
}
export function getComparison(id: string, signal?: AbortSignal) {
  return request<SavedComparison>(`/comparisons/${id}`, { signal });
}
export function getComparisonStatus(id: string, signal?: AbortSignal) {
  return request<{ id: string; status: string; generation: number; updated_at: string; ready_count: number }>(`/comparisons/${id}/status`, { signal });
}
export function uploadComparison(form: FormData, signal?: AbortSignal) {
  return request<SavedComparison>("/comparisons/upload", { method: "POST", body: form, signal });
}
export function updateComparison(id: string, value: { name: string; goal: string; paper_ids: string[]; version: number }, signal?: AbortSignal) {
  return request<SavedComparison>(`/comparisons/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(value), signal });
}
export function generateComparison(id: string, version: number, requestId: string, signal?: AbortSignal) {
  return request<SavedComparison>(`/comparisons/${id}/generate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version, request_id: requestId }), signal });
}
export function retryComparisonPaper(id: string, paperId: string, signal?: AbortSignal) {
  return request<SavedComparison>(`/comparisons/${id}/retry-paper/${paperId}`, { method: "POST", signal });
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

export type SavedProject = Pick<ResearchProject, "id" | "name" | "question" | "status" | "updated_at"> & { paper_count: number };
export function listSavedProjects(signal?: AbortSignal) {
  return request<SavedProject[]>("/research-workflows", { signal });
}
export function renameProject(id: string, name: string, signal?: AbortSignal) {
  return request<ResearchProject>(`/research-workflows/${id}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }), signal,
  });
}
export function saveProjectSelection(id: string, candidateIds: string[], version: number, signal?: AbortSignal) {
  return request<ResearchProject>(`/research-workflows/${id}/selection`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ candidate_ids: candidateIds, version }), signal,
  });
}

export async function getResearchWorkflowStatus(projectId: string, signal?: AbortSignal): Promise<ResearchProjectStatus> {
  return request<ResearchProjectStatus>(`/research-workflows/${projectId}/status`, { signal });
}

export async function retryJob(jobId: string, signal?: AbortSignal): Promise<Job> {
  return request<Job>(`/jobs/${jobId}/retry`, { method: "POST", signal });
}

export async function excludeResearchWorkflowCandidate(
  projectId: string,
  candidateId: string,
  signal?: AbortSignal,
): Promise<ResearchProject> {
  return request<ResearchProject>(`/research-workflows/${projectId}/candidates/${candidateId}`, {
    method: "DELETE",
    signal,
  });
}

export async function excludeResearchWorkflowPaper(
  projectId: string,
  paperId: string,
  signal?: AbortSignal,
): Promise<ResearchProject> {
  return request<ResearchProject>(`/research-workflows/${projectId}/papers/${paperId}`, {
    method: "DELETE",
    signal,
  });
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
