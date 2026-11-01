import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import type { Job, LibraryPaper } from "../types";
import { BatchSummaryPage } from "./BatchSummaryPage";

vi.mock("../lib/api", () => ({
  analyzePaper: vi.fn(),
  batchUploadPapers: vi.fn(),
  createBatchSummary: vi.fn(),
  getPaperStatus: vi.fn(),
}));

const timestamp = "2026-10-03T00:00:00Z";

function paper(id: string, title: string): LibraryPaper {
  return {
    id,
    source: "upload",
    title,
    authors: ["A. Researcher"],
    status: "ready",
    analysis_generation: 1,
    analysis_mode: "ai",
    created_at: timestamp,
    updated_at: timestamp,
  };
}

function uploadJob(id: string, paperId: string): Job {
  return {
    id,
    paper_id: paperId,
    job_type: "analysis",
    status: "completed",
    idempotency_key: `analysis:${paperId}:1`,
    attempt_count: 1,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

describe("BatchSummaryPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows a focused first-use state", () => {
    render(<MemoryRouter><BatchSummaryPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Build a research matrix from a collection of PDFs." })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No comparison loaded" })).toBeInTheDocument();
  });

  it("renders dimensions as rows and papers as columns", async () => {
    const first = paper("paper-1", "Retrieval Study");
    const second = paper("paper-2", "Fine-tuning Study");
    vi.mocked(api.batchUploadPapers).mockResolvedValue({
      items: [
        { paper: first, job: uploadJob("job-1", first.id) },
        { paper: second, job: uploadJob("job-2", second.id) },
      ],
    });
    vi.mocked(api.createBatchSummary).mockResolvedValue({
      overall_takeaway: "The papers evaluate different adaptation strategies.",
      generation_mode: "ai",
      warnings: [],
      papers: [
        {
          paper_id: first.id,
          title: first.title,
          main_idea: "Ground answers with retrieved evidence.",
          problem_or_hypothesis: "Retrieval may reduce unsupported answers.",
          experiments: "Retrieval and no-retrieval baselines.",
          models_and_datasets: "A question-answering benchmark.",
          results: "Grounding improved.",
          conclusions: "Relevant evidence helps.",
        },
        {
          paper_id: second.id,
          title: second.title,
          main_idea: "Adapt a model with domain examples.",
          problem_or_hypothesis: "Fine-tuning may improve domain accuracy.",
          experiments: "Base and adapted model comparison.",
          models_and_datasets: "A domain corpus and evaluation set.",
          results: "Domain accuracy improved.",
          conclusions: "Adaptation helps domain tasks.",
        },
      ],
    });
    const user = userEvent.setup();
    render(<MemoryRouter><BatchSummaryPage /></MemoryRouter>);

    const input = screen.getByLabelText("PDF collection");
    await user.upload(input, [
      new File(["first"], "first.pdf", { type: "application/pdf" }),
      new File(["second"], "second.pdf", { type: "application/pdf" }),
    ]);
    await user.click(screen.getByRole("button", { name: "Upload and compare" }));

    const matrix = await screen.findByRole("table", { name: "Paper comparison matrix" });
    expect(within(matrix).getByRole("columnheader", { name: "Retrieval Study" })).toBeInTheDocument();
    expect(within(matrix).getByRole("columnheader", { name: "Fine-tuning Study" })).toBeInTheDocument();
    expect(within(matrix).getByRole("rowheader", { name: "Results" })).toBeInTheDocument();
    expect(within(matrix).getByText("Grounding improved.")).toBeInTheDocument();
    expect(within(matrix).getByText("Domain accuracy improved.")).toBeInTheDocument();
  });
});
