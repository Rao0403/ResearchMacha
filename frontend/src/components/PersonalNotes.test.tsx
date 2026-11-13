import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PersonalNotes } from "./PersonalNotes";
import * as api from "../lib/api";
import type { PersonalNote } from "../types";

vi.mock("../lib/api", () => ({ listPersonalNotes: vi.fn(), savePersonalNote: vi.fn(), deletePersonalNote: vi.fn() }));
const note: PersonalNote = { id:"note",paper_id:"paper",body:"My own critique",page:3,excerpt:"An exact selected passage",version:1,created_at:"2026-11-13T00:00:00Z",updated_at:"2026-11-13T00:00:00Z" };

describe("Personal notes", () => {
  beforeEach(() => { vi.clearAllMocks(); sessionStorage.clear(); vi.mocked(api.listPersonalNotes).mockResolvedValue([]); });

  it("saves a page-linked personal note, edits it, and confirms deletion", async () => {
    vi.mocked(api.savePersonalNote).mockResolvedValue(note);
    vi.mocked(api.deletePersonalNote).mockResolvedValue({deleted:note.id});
    const onPageClick=vi.fn();
    render(<PersonalNotes paperId="paper" currentPage={9} selectedPage={3} selectedExcerpt="An exact selected passage" onPageClick={onPageClick} />);
    const user=userEvent.setup();
    await screen.findByText("No personal notes saved yet.");
    await user.type(screen.getByLabelText("Your note"),note.body);
    await user.click(screen.getByRole("button",{name:"Use selected source passage"}));
    await user.click(screen.getByRole("button",{name:"Save note"}));
    await screen.findByText("Note saved to your workspace.");
    expect(api.savePersonalNote).toHaveBeenCalledWith("paper",expect.objectContaining({body:note.body,page:3,excerpt:note.excerpt}),expect.any(AbortSignal));
    await user.click(screen.getByRole("button",{name:"p.3"}));
    expect(onPageClick).toHaveBeenCalledWith(3);
    await user.click(screen.getByRole("button",{name:"Edit note"}));
    await user.type(screen.getByLabelText("Your note")," Updated.");
    vi.mocked(api.savePersonalNote).mockResolvedValue({...note,body:note.body+" Updated.",version:2});
    await user.click(screen.getByRole("button",{name:"Save note"}));
    await screen.findByText(note.body+" Updated.");
    expect(vi.mocked(api.savePersonalNote).mock.calls[1][1].version).toBe(1);
    await user.click(screen.getByRole("button",{name:"Delete note"}));
    expect(api.deletePersonalNote).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button",{name:"Confirm delete"}));
    await screen.findByText("Note deleted.");
    expect(vi.mocked(api.deletePersonalNote).mock.calls[0][1].version).toBe(2);
  });

  it("keeps a rejected draft and restores it after reopening", async () => {
    vi.mocked(api.savePersonalNote).mockRejectedValue(new Error("This note changed in another request."));
    const props={paperId:"paper",currentPage:1,onPageClick:vi.fn()};
    const view=render(<PersonalNotes {...props} />);
    const user=userEvent.setup();
    await screen.findByText("No personal notes saved yet.");
    await user.type(screen.getByLabelText("Your note"),"Do not lose my hypothesis");
    await user.click(screen.getByRole("button",{name:"Save note"}));
    await screen.findByRole("alert");
    expect(screen.getByLabelText("Your note")).toHaveValue("Do not lose my hypothesis");
    await waitFor(() => expect(sessionStorage.getItem("research-macha:note-draft:paper")).toContain("Do not lose my hypothesis"));
    view.unmount();
    render(<PersonalNotes {...props} />);
    expect(screen.getByLabelText("Your note")).toHaveValue("Do not lose my hypothesis");
    expect(api.savePersonalNote).toHaveBeenCalledTimes(1);
  });

  it("does not show one paper's draft under another paper", async () => {
    sessionStorage.setItem("research-macha:note-draft:other",JSON.stringify({id:"other-draft",body:"Other paper's thinking",page:null,excerpt:""}));
    render(<PersonalNotes paperId="paper" currentPage={1} onPageClick={vi.fn()} />);
    expect(screen.getByLabelText("Your note")).toHaveValue("");
    expect(screen.queryByText("Other paper's thinking")).not.toBeInTheDocument();
    await screen.findByText("No personal notes saved yet.");
  });
});
