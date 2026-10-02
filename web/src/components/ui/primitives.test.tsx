import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { ActionButton, Alert, CitationChip, EmptyState, Field, PageHeader, Skeleton, StatusBadge, Tabs } from ".";

describe("shared UI primitives", () => {
  it("exposes accessible labels and state", () => {
    render(
      <>
        <PageHeader eyebrow="Reader" title="Evidence workspace" description="Read cited findings." />
        <Field label="Research question" htmlFor="question" hint="Use a focused question.">
          <input id="question" />
        </Field>
        <ActionButton busy busyLabel="Saving note">Save</ActionButton>
        <StatusBadge status="completed_with_warnings" />
        <Alert tone="warning" title="Degraded result"><p>Extractive evidence is shown.</p></Alert>
        <Skeleton label="Loading paper" />
      </>,
    );

    expect(screen.getByRole("heading", { name: "Evidence workspace" })).toBeInTheDocument();
    expect(screen.getByLabelText("Research question")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Saving note" })).toBeDisabled();
    expect(screen.getByText("completed with warnings")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Loading paper" })).toBeInTheDocument();
  });

  it("supports keyboard tab navigation", () => {
    const onValueChange = vi.fn();
    render(
      <Tabs
        label="Paper views"
        value="notes"
        onValueChange={onValueChange}
        items={[
          { id: "notes", label: "Notes", content: <p>Generated notes</p> },
          { id: "chat", label: "Chat", content: <p>Paper chat</p> },
        ]}
      />,
    );

    fireEvent.keyDown(screen.getByRole("tab", { name: "Notes" }), { key: "ArrowRight" });
    expect(onValueChange).toHaveBeenCalledWith("chat");
  });

  it("renders actionable and non-actionable citations", () => {
    render(
      <MemoryRouter>
        <CitationChip
          citation={{ page: 4, excerpt: "Evidence excerpt", chunk_id: "chunk-1" }}
          paperId="paper-1"
          paperTitle="Grounded Research"
        />
        <CitationChip citation={{ page: 2, excerpt: "Legacy excerpt" }} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: "Open Grounded Research, page 4: Evidence excerpt" })).toHaveAttribute("href", "/reader/paper-1?page=4");
    expect(screen.getByText("Page 2")).toBeInTheDocument();
  });

  it("renders a concise empty state", () => {
    render(<EmptyState title="No papers" description="Upload a paper to begin." actions={<button>Upload PDF</button>} />);
    expect(screen.getByRole("heading", { name: "No papers" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload PDF" })).toBeInTheDocument();
  });
});
