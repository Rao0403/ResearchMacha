import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../lib/api";
import type { SavedComparison } from "../types";
import { BatchSummaryPage } from "./BatchSummaryPage";

vi.mock("../lib/api", () => ({
  listComparisons: vi.fn(), getComparison: vi.fn(), getComparisonStatus: vi.fn(),
  uploadComparison: vi.fn(), updateComparison: vi.fn(), generateComparison: vi.fn(), retryComparisonPaper: vi.fn(),
  listPapers: vi.fn(),
}));

const timestamp = "2026-11-13T00:00:00Z";
function saved(): SavedComparison {
  const papers = ["Retrieval Study", "Fine-tuning Study"].map((title, index) => ({
    id: `paper-${index}`, title, source: "upload", authors: [], status: "ready", analysis_generation: 1,
    analysis_mode: "ai" as const, created_at: timestamp, updated_at: timestamp,
  }));
  return { id: "comparison", name: "My comparison", goal: "Compare methods", status: "done", version: 0,
    generation: 1, result_generation: 1, outdated: false, error_message: null, papers, jobs: [], blocking_items: [],
    created_at: timestamp, updated_at: timestamp, result_json: {
      overall_takeaway: "Different adaptation strategies.", generation_mode: "ai", warnings: [],
      papers: papers.map((p) => ({ paper_id: p.id, title: p.title, main_idea: "A distinct method.", problem_or_hypothesis: "The hypothesis.", experiments: "Controlled evaluations.", models_and_datasets: "Benchmark.", results: `${p.title} result`, conclusions: "Qualified conclusion." })),
    } };
}
function open(path = "/comparisons") {
  const router = createMemoryRouter([
    { path: "/comparisons", element: <BatchSummaryPage /> },
    { path: "/comparisons/:comparisonId", element: <BatchSummaryPage /> },
    { path: "/reader/:paperId", element: <p>Reader destination</p> },
  ], { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

describe("Saved comparisons", () => {
  beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.listComparisons).mockResolvedValue([]); vi.mocked(api.getComparison).mockResolvedValue(saved()); });

  it("shows a first-use state without starting generation", async () => {
    open();
    expect(await screen.findByText("No comparison loaded")).toBeInTheDocument();
    expect(api.generateComparison).not.toHaveBeenCalled();
  });

  it("uploads once and navigates to a saved result with paper comparison columns", async () => {
    vi.mocked(api.uploadComparison).mockResolvedValue(saved());
    const router = open();
    const user = userEvent.setup();
    await user.upload(screen.getByLabelText("PDF collection"), [
      new File(["first"], "first.pdf", { type: "application/pdf" }), new File(["second"], "second.pdf", { type: "application/pdf" }),
    ]);
    expect((screen.getByLabelText("PDF collection") as HTMLInputElement).files).toHaveLength(2);
    expect((screen.getByLabelText("PDF collection") as HTMLInputElement).form?.checkValidity()).toBe(true);
    await user.click(screen.getByRole("button", { name: "Upload and compare" }));
    expect(api.uploadComparison).toHaveBeenCalledTimes(1);
    const matrix = await screen.findByRole("table", { name: "Paper comparison matrix" });
    expect(within(matrix).getByRole("columnheader", { name: "Retrieval Study" })).toBeInTheDocument();
    expect(within(matrix).getByRole("rowheader", { name: "Results" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/comparisons/comparison");
    expect(api.uploadComparison).toHaveBeenCalledTimes(1);
    expect(api.generateComparison).not.toHaveBeenCalled();
  });

  it("creates a comparison from library papers with no PDF uploads", async () => {
    vi.mocked(api.listPapers).mockResolvedValue(saved().papers);
    vi.mocked(api.uploadComparison).mockResolvedValue(saved());
    open();
    const user=userEvent.setup();
    await user.click(screen.getByRole("button",{name:"Choose from library"}));
    await user.click(await screen.findByRole("checkbox",{name:/Retrieval Study/}));
    await user.click(screen.getByRole("checkbox",{name:/Fine-tuning Study/}));
    await user.click(screen.getByRole("button",{name:"Upload and compare"}));
    await screen.findByRole("table",{name:"Paper comparison matrix"});
    const form=vi.mocked(api.uploadComparison).mock.calls[0][0];
    expect(form.getAll("files")).toEqual([]);
    expect(JSON.parse(form.get("library_paper_ids") as string)).toEqual(["paper-0","paper-1"]);
  });

  it("shows comparison limitations and opens the correct paper with source context", async () => {
    const result=saved();
    result.result_json!.papers[0].limitations="Only one dataset was evaluated.";
    result.result_json!.papers[0].comparability="Accuracy uses a fixed test split.";
    result.result_json!.papers[0].citations={results:[{paper_id:"paper-0", title:"Retrieval Study",page:7,excerpt:"Measured result from the experiment.",chunk_id:"source-7"}]};
    vi.mocked(api.getComparison).mockResolvedValue(result);
    const router=open("/comparisons/comparison");
    expect(await screen.findByText("Only one dataset was evaluated.")).toBeInTheDocument();
    expect(screen.getByRole("rowheader",{name:"Evaluation conditions"})).toBeInTheDocument();
    const link=screen.getByRole("link",{name:/Open Retrieval Study, page 7:/});
    expect(link).toHaveAttribute("href","/reader/paper-0?page=7");
    await userEvent.setup().click(link);
    expect(router.state.location.state).toMatchObject({sourcePaperId:"paper-0",sourceExcerpt:"Measured result from the experiment.",sourceReturnTo:"/comparisons/comparison"});
  });

  it("reopens saved output and saves a changed goal without automatically generating", async () => {
    const original = saved();
    vi.mocked(api.updateComparison).mockResolvedValue({ ...original, goal: "New comparison goal", version: 1, generation: 2, status: "draft", outdated: true });
    vi.mocked(api.generateComparison).mockResolvedValue({ ...original, goal: "New comparison goal", version: 1, generation: 3, status: "queued", outdated: true });
    vi.mocked(api.getComparisonStatus).mockResolvedValue({ id: original.id, status: "queued", generation: 3, updated_at: timestamp, ready_count: 2 });
    open("/comparisons/comparison");
    expect(await screen.findByRole("table", { name: "Paper comparison matrix" })).toBeInTheDocument();
    expect(api.uploadComparison).not.toHaveBeenCalled();
    const user = userEvent.setup();
    await user.clear(screen.getByLabelText("Comparison goal"));
    await user.type(screen.getByLabelText("Comparison goal"), "New comparison goal");
    await user.click(screen.getByRole("button", { name: "Save details" }));
    await screen.findByText("Previous result");
    expect(api.generateComparison).not.toHaveBeenCalled();
    expect(screen.getByText("Different adaptation strategies.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Update comparison" }));
    await waitFor(() => expect(api.generateComparison).toHaveBeenCalledTimes(1));
    expect(api.generateComparison).toHaveBeenCalledWith("comparison", 1, expect.any(String), expect.any(AbortSignal));
    expect(screen.getByText("Different adaptation strategies.")).toBeInTheDocument();
  });
});
