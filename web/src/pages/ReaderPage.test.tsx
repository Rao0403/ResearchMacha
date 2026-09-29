import { StrictMode } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import type { PaperDetail, PaperSummaryResponse } from "../types";
import { ReaderPage } from "./ReaderPage";

vi.mock("../components/PdfViewer", () => ({
  PdfViewer: ({ title }: { title: string }) => <div>PDF: {title}</div>,
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
});
