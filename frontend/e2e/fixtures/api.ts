import type { Page, Route } from "@playwright/test";

import type { Job, LibraryPaper, ResearchProject, SavedComparison } from "../../src/types";

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

export const savedComparison: SavedComparison = {
  id: "saved-comparison", name: "Saved evidence comparison", goal: "Compare empirical evidence",
  status: "done", version: 0, generation: 1, result_generation: 1, outdated: false,
  error_message: null, papers: [papersByState[0], { ...papersByState[0], id: "second-paper", title: "Second evidence study" }],
  jobs: [], blocking_items: [], created_at: now, updated_at: now,
  result_json: {
    overall_takeaway: "The studies report complementary evidence.", generation_mode: "ai", warnings: [],
    papers: ["paper-ready", "second-paper"].map((id, index) => ({
      paper_id: id, title: index === 0 ? papersByState[0].title : "Second evidence study",
      main_idea: "Evaluate adaptation.", problem_or_hypothesis: "Does adaptation help?",
      experiments: "Controlled benchmark.", models_and_datasets: "A fixed evaluation set.",
      results: "Measured improvement.", conclusions: "Evidence is limited to this benchmark.",
    })),
  },
};

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

    if (request.method() === "GET" && ["/api/comparisons", "/api/research-workflows"].includes(url.pathname)) {
      await json(route, []);
      return;
    }
    if (request.method() === "GET" && url.pathname === "/api/research-workflows/project-blocked") {
      await json(route, blockedProject);
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/comparisons/upload" ||
        request.method() === "GET" && url.pathname === "/api/comparisons/saved-comparison") {
      await json(route, savedComparison);
      return;
    }

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
