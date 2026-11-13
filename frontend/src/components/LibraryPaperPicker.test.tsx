import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LibraryPaperPicker } from "./LibraryPaperPicker";
import { listPapers } from "../lib/api";

vi.mock("../lib/api", () => ({ listPapers: vi.fn() }));

describe("LibraryPaperPicker", () => {
  it("loads only on demand and offers ready evidence without starting processing", async () => {
    const onChange=vi.fn();
    vi.mocked(listPapers).mockResolvedValue([
      { id:"ready",title:"Reusable study",authors:["Ada"],status:"ready" },
      { id:"failed",title:"Failed study",authors:[],status:"failed" },
    ] as Awaited<ReturnType<typeof listPapers>>);
    render(<LibraryPaperPicker selected={[]} onChange={onChange} />);
    expect(listPapers).not.toHaveBeenCalled();
    const user=userEvent.setup();
    await user.click(screen.getByRole("button",{name:"Choose from library"}));
    await user.click(await screen.findByRole("checkbox",{name:/Reusable study/}));
    expect(onChange).toHaveBeenCalledWith(["ready"]);
    expect(screen.queryByText("Failed study")).not.toBeInTheDocument();
  });
});
