import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import type { LibraryPaper } from "../types";
import { LibraryPage } from "./LibraryPage";

vi.mock("../lib/api", () => ({ listPapers: vi.fn() }));

const papers: LibraryPaper[] = [
  paper("ready", "Grounded retrieval", "ready", "Evidence Author"),
  paper("failed", "Domain adaptation", "failed", "Model Author"),
];

describe("LibraryPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("supports title search and status filtering", async () => {
    vi.mocked(api.listPapers).mockResolvedValue(papers);
    const user = userEvent.setup();
    render(<MemoryRouter><LibraryPage /></MemoryRouter>);

    expect(await screen.findByRole("link", { name: "Grounded retrieval" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Domain adaptation" })).toBeInTheDocument();

    await user.type(screen.getByRole("searchbox", { name: "Search papers" }), "retrieval");
    expect(screen.getByRole("link", { name: "Grounded retrieval" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Domain adaptation" })).not.toBeInTheDocument();

    await user.clear(screen.getByRole("searchbox", { name: "Search papers" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Analysis status" }), "failed");
    expect(screen.queryByRole("link", { name: "Grounded retrieval" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Domain adaptation" })).toBeInTheDocument();
  });

  it("provides a productive empty state", async () => {
    vi.mocked(api.listPapers).mockResolvedValue([]);
    render(<MemoryRouter><LibraryPage /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Your library is empty" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Upload your first paper" })).toHaveAttribute("href", "/reader");
  });
});

function paper(id: string, title: string, status: string, author: string): LibraryPaper {
  return {
    id,
    source: "upload",
    title,
    authors: [author],
    abstract: `${title} abstract`,
    year: 2026,
    status,
    analysis_generation: status === "ready" ? 1 : 0,
    analysis_mode: status === "ready" ? "ai" : "unknown_legacy",
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-02T00:00:00Z",
  };
}
