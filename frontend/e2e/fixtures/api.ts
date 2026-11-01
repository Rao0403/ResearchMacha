import type { Page, Route } from "@playwright/test";

import type { Job, LibraryPaper, ResearchProject } from "../../src/types";

const now = "2026-10-02T10:00:00Z";

function paper(id: string, status: string, mode: LibraryPaper["analysis_mode"]): LibraryPaper {
  return {
    id,
    source: "upload",
    title: `Fixture paper: ${status}`,
    authors: ["Ada Researcher", "Grace Scholar"],
    abstract: `Deterministic ${status} paper used by the browser UI harness.`,
    year: 2026,
    status,
    analysis_generation: status === "processing" ? 0 : 1,
    analysis_mode: mode,
    analysis_warning: status === "degraded" ? "The model was unavailable; extractive notes are shown." : null,
    created_at: now,
    updated_at: now,
    last_opened_at: null,
  };
}

export const papersByState: LibraryPaper[] = [
  paper("paper-ready", "ready", "ai"),
  paper("paper-processing", "processing", "unknown_legacy"),
  paper("paper-degraded", "degraded", "extractive"),
  paper("paper-failed", "failed", "unknown_legacy"),
];

const failedJob: Job = {
  id: "job-failed",
  project_id: "project-blocked",
  candidate_id: "candidate-failed",
  paper_id: null,
  job_type: "import",
  status: "failed",
  idempotency_key: "fixture:blocked",
  attempt_count: 1,
  error_message: "Fixture download failed.",
  warning_message: null,
  payload: null,
  created_at: now,
  updated_at: now,
  started_at: now,
  finished_at: now,
};

export const blockedProject: ResearchProject = {
  id: "project-blocked",
  question: "How should domain evidence be evaluated?",
  status: "blocked",
  generated_queries: ["domain evidence evaluation"],
  inclusion_criteria: ["Reports an empirical evaluation"],
  synthesis_json: null,
  synthesis_generation: 0,
  created_at: now,
  updated_at: now,
  candidates: [
    {
      id: "candidate-failed",
      project_id: "project-blocked",
      arxiv_id: "2601.00001",
      title: "A deterministic browser fixture",
      authors: ["Ada Researcher"],
      abstract: "A stable candidate used to exercise blocked workflow presentation.",
      year: 2026,
      pdf_url: "https://example.test/paper.pdf",
      entry_url: "https://example.test/paper",
      score: 88,
      rationale: "Matches the fixture research question.",
      selected: true,
      created_at: now,
    },
  ],
  papers: [],
  memory_signals: [],
  recent_jobs: [failedJob],
  blocking_items: [
    {
      target_type: "candidate",
      target_id: "candidate-failed",
      title: "A deterministic browser fixture",
      job_id: failedJob.id,
      error: failedJob.error_message,
    },
  ],
};

export async function installApiFixtures(page: Page) {
  await page.route("http://localhost:8000/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (request.method() === "GET" && url.pathname === "/api/papers") {
      await json(route, papersByState);
      return;
    }

    if (request.method() === "POST" && url.pathname === "/api/research-workflows") {
      await json(route, blockedProject);
      return;
    }

    await json(route, { detail: `Unhandled browser fixture: ${request.method()} ${url.pathname}` }, 404);
  });
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}
