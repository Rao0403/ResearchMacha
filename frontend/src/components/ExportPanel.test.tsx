import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../lib/api";
import { ExportPanel } from "./ExportPanel";

vi.mock("../lib/api",()=>({getExportOptions:vi.fn(),downloadSavedWork:vi.fn()}));
describe("ExportPanel",()=>{
  beforeEach(()=>{
    vi.clearAllMocks();
    URL.createObjectURL=vi.fn(()=>"blob:saved-export");URL.revokeObjectURL=vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype,"click").mockImplementation(()=>{});
    vi.mocked(api.getExportOptions).mockResolvedValue({has_result:true,paper_count:2,warnings:[],notes:[
      {id:"chosen",paper_id:"p1",paper_title:"Study one",page:2,preview:"My critique"},
      {id:"other",paper_id:"p2",paper_title:"Study two",page:null,preview:"Another thought"},
    ]});
    vi.mocked(api.downloadSavedWork).mockResolvedValue({blob:new Blob(["Saved result"]),filename:"research.md"});
  });
  afterEach(()=>vi.restoreAllMocks());

  it("only loads options on demand and includes explicitly selected personal notes",async()=>{
    render(<ExportPanel kind="research" id="project"/>);
    expect(api.getExportOptions).not.toHaveBeenCalled();
    const user=userEvent.setup();
    await user.click(screen.getByRole("button",{name:"Export",exact:true}));
    await user.click(await screen.findByRole("checkbox",{name:/Study one/}));
    await user.click(screen.getByRole("button",{name:"Download Markdown"}));
    await screen.findByText("Download prepared from saved data. No model calls were made.");
    expect(api.downloadSavedWork).toHaveBeenCalledWith("research","project","markdown",["chosen"],expect.any(AbortSignal));
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  });
  it("offers BibTeX before generation without enabling a nonexistent result export",async()=>{
    vi.mocked(api.getExportOptions).mockResolvedValue({has_result:false,paper_count:2,warnings:[],notes:[]});
    render(<ExportPanel kind="comparison" id="comparison"/>);
    const user=userEvent.setup();await user.click(screen.getByRole("button",{name:"Export",exact:true}));
    expect(await screen.findByRole("button",{name:"Download CSV"})).toBeDisabled();
    expect(screen.getByRole("button",{name:"Download Markdown"})).toBeDisabled();
    await user.click(screen.getByRole("button",{name:"Download BibTeX"}));
    await waitFor(()=>expect(api.downloadSavedWork).toHaveBeenCalledWith("comparison","comparison","bibtex",[],expect.any(AbortSignal)));
  });
  it("keeps the selection on a download error and never retries automatically",async()=>{
    vi.mocked(api.downloadSavedWork).mockRejectedValue(new Error("Result unavailable"));
    render(<ExportPanel kind="paper" id="paper"/>);
    const user=userEvent.setup();await user.click(screen.getByRole("button",{name:"Export",exact:true}));
    await user.click(await screen.findByRole("checkbox",{name:/Study one/}));
    await user.click(screen.getByRole("button",{name:"Download Markdown"}));
    await screen.findByRole("alert");
    expect(screen.getByRole("checkbox",{name:/Study one/})).toBeChecked();
    expect(api.downloadSavedWork).toHaveBeenCalledTimes(1);
  });
  it("refreshes export readiness when background generation finishes without starting downloads",async()=>{
    vi.mocked(api.getExportOptions).mockResolvedValue({has_result:false,paper_count:2,warnings:[],notes:[]});
    const view=render(<ExportPanel kind="comparison" id="comparison" revision="pending"/>);
    await userEvent.setup().click(screen.getByRole("button",{name:"Export",exact:true}));
    expect(await screen.findByRole("button",{name:"Download Markdown"})).toBeDisabled();
    vi.mocked(api.getExportOptions).mockResolvedValue({has_result:true,paper_count:2,warnings:[],notes:[]});
    view.rerender(<ExportPanel kind="comparison" id="comparison" revision="done"/>);
    await waitFor(()=>expect(screen.getByRole("button",{name:"Download Markdown"})).toBeEnabled());
    expect(api.downloadSavedWork).not.toHaveBeenCalled();
  });
});
