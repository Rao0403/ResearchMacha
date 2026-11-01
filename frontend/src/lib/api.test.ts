import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  excludeResearchWorkflowCandidate,
  excludeResearchWorkflowPaper,
  getPaperStatus,
  retryJob,
} from "./api";

describe("API client contracts", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses the lightweight status endpoint and forwards AbortSignal", async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "paper-1",
          status: "processing",
          analysis_generation: 1,
          analysis_mode: "ai",
          analysis_warning: null,
          active_job: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const status = await getPaperStatus("paper-1", controller.signal);

    expect(status.status).toBe("processing");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/papers/paper-1/status",
      expect.objectContaining({ signal: controller.signal }),
    );
  });

  it("normalizes structured FastAPI errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ detail: { code: "pdf_too_large", message: "PDF exceeds the upload limit" } }),
          { status: 413, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    const request = getPaperStatus("paper-1");

    await expect(request).rejects.toMatchObject<ApiError>({
      name: "ApiError",
      message: "PDF exceeds the upload limit",
      status: 413,
      code: "pdf_too_large",
    });
  });

  it("normalizes FastAPI validation errors into a readable message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ detail: [{ loc: ["body", "question"], msg: "Field required", type: "missing" }] }),
          { status: 422, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(getPaperStatus("paper-1")).rejects.toThrow("Field required");
  });

  it("calls the workflow recovery endpoints with the expected methods", async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn().mockImplementation(async () => (
      new Response(JSON.stringify({ id: "result" }), { status: 200, headers: { "Content-Type": "application/json" } })
    ));
    vi.stubGlobal("fetch", fetchMock);

    await retryJob("job-1", controller.signal);
    await excludeResearchWorkflowCandidate("project-1", "candidate-1", controller.signal);
    await excludeResearchWorkflowPaper("project-1", "paper-1", controller.signal);

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://localhost:8000/api/jobs/job-1/retry", {
      method: "POST",
      signal: controller.signal,
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://localhost:8000/api/research-workflows/project-1/candidates/candidate-1", {
      method: "DELETE",
      signal: controller.signal,
    });
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://localhost:8000/api/research-workflows/project-1/papers/paper-1", {
      method: "DELETE",
      signal: controller.signal,
    });
  });
});
