import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import type { Job, ResearchProject } from "../types";
import { ResearchWorkflowPage } from "./ResearchWorkflowPage";

vi.mock("../lib/api", () => ({
  approveResearchWorkflow: vi.fn(),
  createResearchWorkflow: vi.fn(),
  excludeResearchWorkflowCandidate: vi.fn(),
  excludeResearchWorkflowPaper: vi.fn(),
  getResearchWorkflow: vi.fn(),
  getResearchWorkflowStatus: vi.fn(),
  retryJob: vi.fn(),
}));

const timestamp = "2026-01-01T00:00:00Z";

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-1",
    project_id: "project-1",
    candidate_id: "candidate-1",
    job_type: "import",
    status: "failed",
    idempotency_key: "import:project-1:candidate-1",
    attempt_count: 1,
    error_message: "arXiv download failed",
    created_at: timestamp,
    updated_at: timestamp,
    ...overrides,
  };
}

function project(overrides: Partial<ResearchProject> = {}): ResearchProject {
  return {
    id: "project-1",
    question: "How does retrieval improve factuality?",
    status: "blocked",
    generated_queries: ["retrieval factuality"],
    inclusion_criteria: ["Empirical evidence"],
    synthesis_generation: 1,
    created_at: timestamp,
    updated_at: timestamp,
    candidates: [{
      id: "candidate-1",
      project_id: "project-1",
      arxiv_id: "2601.00001",
      title: "Failed candidate",
      authors: ["A. Researcher"],
      abstract: "Evidence",
      year: 2026,
      pdf_url: "https://example.test/paper.pdf",
      entry_url: "https://example.test/paper",
      score: 91,
      rationale: "Relevant evidence",
      selected: true,
      created_at: timestamp,
    }],
    papers: [],
    agent_run: null,
    memory_signals: [],
    recent_jobs: [job()],
    blocking_items: [{
      target_type: "candidate",
      target_id: "candidate-1",
      title: "Failed candidate",
      job_id: "job-1",
      error: "arXiv download failed",
    }],
    ...overrides,
  };
}

async function startWorkflow(nextProject: ResearchProject) {
  vi.mocked(api.createResearchWorkflow).mockResolvedValue(nextProject);
  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <ResearchWorkflowPage />
    </MemoryRouter>,
  );
  await user.type(screen.getByLabelText("Research question"), "How does retrieval improve factuality?");
  await user.click(screen.getByRole("button", { name: "Start research" }));
  await screen.findByRole("heading", { name: "Recommended papers" });
  return user;
}

describe("ResearchWorkflowPage reliability controls", () => {
  beforeEach(() => vi.clearAllMocks());

  it("retries a failed blocker and refreshes the project", async () => {
    const blockedProject = project();
    const resumedProject = project({ status: "importing", blocking_items: [], recent_jobs: [job({ status: "queued", error_message: null })] });
    vi.mocked(api.retryJob).mockResolvedValue(job({ status: "queued", error_message: null }));
    vi.mocked(api.getResearchWorkflow).mockResolvedValue(resumedProject);
    const user = await startWorkflow(blockedProject);

    expect(screen.getByRole("heading", { name: "Resolve failed work before synthesis" })).toBeInTheDocument();
    expect(screen.getByText("arXiv download failed")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(api.retryJob).toHaveBeenCalledWith("job-1", expect.any(AbortSignal)));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Resolve failed work before synthesis" })).not.toBeInTheDocument());
  });

  it("excludes a failed candidate from only the current workflow", async () => {
    const blockedProject = project();
    const withoutCandidate = project({
      status: "awaiting_approval",
      candidates: [],
      blocking_items: [],
      recent_jobs: [],
    });
    vi.mocked(api.excludeResearchWorkflowCandidate).mockResolvedValue(withoutCandidate);
    const user = await startWorkflow(blockedProject);

    await user.click(screen.getByRole("button", { name: "Exclude" }));

    await waitFor(() => expect(api.excludeResearchWorkflowCandidate).toHaveBeenCalledWith(
      "project-1",
      "candidate-1",
      expect.any(AbortSignal),
    ));
    expect(screen.queryByText("arXiv download failed")).not.toBeInTheDocument();
  });

  it("excludes a failed analysis paper without deleting the library paper", async () => {
    const failedAnalysis = job({
      id: "analysis-job",
      candidate_id: null,
      paper_id: "paper-1",
      job_type: "analysis",
      idempotency_key: "analysis:paper-1:1",
      error_message: "PDF extraction failed",
    });
    const failedProject = project({
      candidates: [],
      papers: [{
        id: "paper-1",
        source: "arxiv",
        title: "Failed analysis paper",
        authors: ["A. Researcher"],
        status: "failed",
        analysis_generation: 0,
        analysis_mode: "unknown_legacy",
        analysis_warning: "PDF extraction failed",
        created_at: timestamp,
        updated_at: timestamp,
      }],
      recent_jobs: [failedAnalysis],
      blocking_items: [{
        target_type: "paper",
        target_id: "paper-1",
        title: "Failed analysis paper",
        job_id: "analysis-job",
        error: "PDF extraction failed",
      }],
    });
    vi.mocked(api.excludeResearchWorkflowPaper).mockResolvedValue(project({
      status: "awaiting_approval",
      candidates: [],
      papers: [],
      recent_jobs: [],
      blocking_items: [],
    }));
    const user = await startWorkflow(failedProject);

    expect(screen.getByText("PDF extraction failed")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Exclude" }));

    await waitFor(() => expect(api.excludeResearchWorkflowPaper).toHaveBeenCalledWith(
      "project-1",
      "paper-1",
      expect.any(AbortSignal),
    ));
  });

  it("labels a degraded brief and links citations to the exact paper page", async () => {
    const degradedProject = project({
      status: "degraded",
      candidates: [],
      blocking_items: [],
      recent_jobs: [job({
        id: "warning-job",
        candidate_id: null,
        paper_id: "paper-1",
        job_type: "analysis",
        status: "completed_with_warnings",
        warning_message: "The previous successful analysis was retained.",
        error_message: null,
      })],
      synthesis_json: {
        executive_summary: "A source-extractive evidence packet.",
        key_findings: [{
          label: "Finding",
          summary: "Retrieval improved grounding.",
          citations: [{
            paper_id: "paper-1",
            title: "Grounded Retrieval",
            page: 7,
            excerpt: "Retrieval improved grounding in the evaluation.",
            chunk_id: "chunk-7",
          }],
        }],
        evidence_table: [],
        conflicts_or_gaps: [],
        suggested_experiments: [],
        suggested_research_directions: [],
        generation_mode: "extractive",
        warnings: ["AI synthesis was unavailable."],
      },
    });

    await startWorkflow(degradedProject);

    expect(screen.getByText("Extractive fallback")).toBeInTheDocument();
    expect(screen.getByText("AI synthesis was unavailable.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Job warnings and recovery" })).toBeInTheDocument();
    expect(screen.getByText("The previous successful analysis was retained.")).toBeInTheDocument();
    const citation = screen.getByRole("link", { name: /Grounded Retrieval.*Page 7.*Retrieval improved grounding/i });
    expect(citation).toHaveAttribute("href", "/reader/paper-1?page=7");
  });

  it("lets a researcher review and approve a candidate with accessible controls", async () => {
    const awaitingProject = project({ status: "awaiting_approval", blocking_items: [], recent_jobs: [] });
    const importingProject = project({ status: "importing", blocking_items: [], recent_jobs: [] });
    vi.mocked(api.approveResearchWorkflow).mockResolvedValue(importingProject);
    const user = await startWorkflow(awaitingProject);

    const checkbox = screen.getByRole("checkbox", { name: "Select Failed candidate" });
    expect(checkbox).toBeChecked();
    await user.click(checkbox);
    expect(screen.getByRole("button", { name: "Approve selected papers" })).toBeDisabled();
    await user.click(checkbox);
    await user.click(screen.getByRole("button", { name: "Approve selected papers" }));

    await waitFor(() => expect(api.approveResearchWorkflow).toHaveBeenCalledWith(
      "project-1",
      ["candidate-1"],
      expect.any(AbortSignal),
    ));
  });
});
