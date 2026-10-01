import { StrictMode } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import type { Job, PaperDetail, PaperSummaryResponse } from "../types";
import { ReaderPage } from "./ReaderPage";

vi.mock("../components/PdfViewer", () => ({
  PdfViewer: ({ title, targetPage }: { title: string; targetPage?: number | null }) => (
    <div>PDF: {title}{targetPage ? `, target page ${targetPage}` : ""}</div>
  ),
}));

vi.mock("../lib/api", () => ({
  analyzePaper: vi.fn(),
  getPaper: vi.fn(),
  getPaperStatus: vi.fn(),
  getPaperSummary: vi.fn(),
  getPdfUrl: vi.fn((paperId: string) => `/papers/${paperId}.pdf`),
  sendChatMessage: vi.fn(),
  uploadPaper: vi.fn(),
}));

function paper(id: string, title: string): PaperDetail {
  return {
    id,
    source: "upload",
    title,
    authors: [],
    status: "ready",
    analysis_generation: 1,
    analysis_mode: "ai",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    chunks: [],
    highlights: [],
  };
}

function summary(value: string, sourcePaper: PaperDetail): PaperSummaryResponse {
  const generatedSummary = {
    problem_or_hypothesis: value,
    approach: value,
    experiments: value,
    results: value,
    conclusion: value,
    limitations_or_notes: value,
    section_citations: {},
    generation_mode: "ai" as const,
  };
  return { paper: sourcePaper, summary: generatedSummary, highlights: [] };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

describe("ReaderPage request scoping", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.useRealTimers());

  it("clears old paper state and ignores a late summary after a route switch", async () => {
    const oldPaper = paper("old", "Old paper");
    const newPaper = paper("new", "New paper");
    const oldSummary = deferred<PaperSummaryResponse>();
    vi.mocked(api.getPaper).mockImplementation(async (paperId) => paperId === "old" ? oldPaper : newPaper);
    vi.mocked(api.getPaperSummary).mockImplementation((paperId) => (
      paperId === "old" ? oldSummary.promise : Promise.resolve(summary("New evidence", newPaper))
    ));
    const router = createMemoryRouter(
      [{ path: "/reader/:paperId", element: <ReaderPage /> }],
      { initialEntries: ["/reader/old"] },
    );

    render(<RouterProvider router={router} />);
    expect(await screen.findByRole("heading", { name: "Old paper" })).toBeInTheDocument();
    await act(async () => { await router.navigate("/reader/new"); });

    expect(screen.queryByRole("heading", { name: "Old paper" })).not.toBeInTheDocument();
    oldSummary.resolve(summary("Stale evidence", oldPaper));
    await act(async () => oldSummary.promise);
    expect(screen.queryByText("Stale evidence")).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "New paper" })).toBeInTheDocument();
    expect(await screen.findAllByText("New evidence")).not.toHaveLength(0);
  });

  it("does not start duplicate summary requests during a StrictMode mount", async () => {
    const readyPaper = paper("paper-1", "Strict paper");
    vi.mocked(api.getPaper).mockResolvedValue(readyPaper);
    vi.mocked(api.getPaperSummary).mockResolvedValue(summary("Strict evidence", readyPaper));
    const router = createMemoryRouter(
      [{ path: "/reader/:paperId", element: <ReaderPage /> }],
      { initialEntries: ["/reader/paper-1"] },
    );

    render(
      <StrictMode>
        <RouterProvider router={router} />
      </StrictMode>,
    );

    await screen.findByRole("heading", { name: "Strict paper" });
    await waitFor(() => expect(api.getPaperSummary).toHaveBeenCalledTimes(1));
  });

  it("loads the summary before stopping polling on a degraded terminal transition", async () => {
    vi.useFakeTimers();
    const queuedPaper = { ...paper("paper-1", "Fallback paper"), status: "processing" };
    const degradedPaper = {
      ...paper("paper-1", "Fallback paper"),
      status: "degraded",
      analysis_mode: "extractive" as const,
      analysis_warning: "AI summary unavailable; source-extractive fallback used.",
    };
    vi.mocked(api.getPaper)
      .mockResolvedValueOnce(queuedPaper)
      .mockResolvedValueOnce(degradedPaper);
    vi.mocked(api.getPaperStatus).mockResolvedValue({
      id: "paper-1",
      status: "degraded",
      analysis_generation: 1,
      analysis_mode: "extractive",
      analysis_warning: degradedPaper.analysis_warning,
      active_job: null,
    });
    vi.mocked(api.getPaperSummary).mockResolvedValue(summary("Extractive evidence", degradedPaper));
    const router = createMemoryRouter(
      [{ path: "/reader/:paperId", element: <ReaderPage /> }],
      { initialEntries: ["/reader/paper-1"] },
    );

    render(<RouterProvider router={router} />);
    await act(async () => undefined);
    expect(screen.getAllByText("processing")).not.toHaveLength(0);

    await act(async () => vi.advanceTimersByTimeAsync(3500));

    expect(api.getPaperStatus).toHaveBeenCalledTimes(1);
    expect(api.getPaper).toHaveBeenCalledTimes(2);
    expect(api.getPaperSummary).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText("Extractive evidence")).not.toHaveLength(0);
    expect(screen.getAllByText("degraded")).not.toHaveLength(0);
    expect(screen.getByText("Paper analysis warning")).toBeInTheDocument();
    expect(screen.getByText(degradedPaper.analysis_warning)).toBeInTheDocument();

    await act(async () => vi.advanceTimersByTimeAsync(7000));
    expect(api.getPaperStatus).toHaveBeenCalledTimes(1);
  });

  it("passes a citation page from the URL to the PDF viewer", async () => {
    const readyPaper = paper("paper-1", "Linked paper");
    vi.mocked(api.getPaper).mockResolvedValue(readyPaper);
    vi.mocked(api.getPaperSummary).mockResolvedValue(summary("Linked evidence", readyPaper));
    const router = createMemoryRouter(
      [{ path: "/reader/:paperId", element: <ReaderPage /> }],
      { initialEntries: ["/reader/paper-1?page=7"] },
    );

    render(<RouterProvider router={router} />);

    expect(await screen.findByText("PDF: Linked paper, target page 7")).toBeInTheDocument();
  });

  it("keeps the previous summary visible while degraded analysis is retried", async () => {
    const degradedPaper = {
      ...paper("paper-1", "Retried paper"),
      status: "degraded",
      analysis_mode: "extractive" as const,
      analysis_warning: "AI summary was unavailable.",
    };
    vi.mocked(api.getPaper).mockResolvedValue(degradedPaper);
    vi.mocked(api.getPaperSummary).mockResolvedValue(summary("Previous successful evidence", degradedPaper));
    vi.mocked(api.analyzePaper).mockResolvedValue({ id: "job-1" } as Job);
    const router = createMemoryRouter(
      [{ path: "/reader/:paperId", element: <ReaderPage /> }],
      { initialEntries: ["/reader/paper-1"] },
    );
    const user = userEvent.setup();

    render(<RouterProvider router={router} />);
    expect(await screen.findAllByText("Previous successful evidence")).not.toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Retry analysis" }));

    expect(api.analyzePaper).toHaveBeenCalledWith("paper-1", expect.any(AbortSignal));
    expect(screen.getAllByText("Previous successful evidence")).not.toHaveLength(0);
    expect(screen.getAllByText("processing")).not.toHaveLength(0);
  });
});
