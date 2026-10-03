import { FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { GenerationNotice } from "../components/GenerationNotice";
import { ActionButton, Alert, EmptyState, Field, PageHeader, StatusBadge, Surface } from "../components/ui";
import { useSingleFlightPolling } from "../hooks/useSingleFlightPolling";
import { analyzePaper, batchUploadPapers, createBatchSummary, getPaperStatus } from "../lib/api";
import type { BatchPaperSummary, BatchSummaryResponse, LibraryPaper } from "../types";

type ComparisonKey = Exclude<keyof BatchPaperSummary, "paper_id" | "title">;

const comparisonDimensions: Array<{ key: ComparisonKey; label: string }> = [
  { key: "main_idea", label: "Main idea" },
  { key: "problem_or_hypothesis", label: "Problem / hypothesis" },
  { key: "experiments", label: "Experiments" },
  { key: "models_and_datasets", label: "Models / datasets" },
  { key: "results", label: "Results" },
  { key: "conclusions", label: "Conclusions" },
];

export function BatchSummaryPage() {
  const [papers, setPapers] = useState<LibraryPaper[]>([]);
  const [summary, setSummary] = useState<BatchSummaryResponse | null>(null);
  const [goal, setGoal] = useState("Extract the main ideas, hypothesis, experiments, models, datasets, results, and conclusions.");
  const [uploading, setUploading] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
  const [retryingIds, setRetryingIds] = useState<Set<string>>(new Set());
  const [message, setMessage] = useState<string | null>(null);
  const papersRef = useRef(papers);
  const batchRevisionRef = useRef(0);
  const uploadControllerRef = useRef<AbortController | null>(null);
  const summaryControllerRef = useRef<AbortController | null>(null);
  const retryControllersRef = useRef(new Map<string, AbortController>());
  const summaryStartedKeyRef = useRef<string | null>(null);
  papersRef.current = papers;

  const batchIdentity = getBatchIdentity(papers);
  const hasRunningPapers = papers.some((paper) => !["ready", "degraded", "failed"].includes(paper.status));
  const allPapersReady = papers.length > 0 && papers.every((paper) => ["ready", "degraded"].includes(paper.status));
  const failedPaperCount = papers.filter((paper) => paper.status === "failed").length;

  useEffect(() => {
    return () => {
      batchRevisionRef.current += 1;
      uploadControllerRef.current?.abort();
      summaryControllerRef.current?.abort();
      retryControllersRef.current.forEach((controller) => controller.abort());
      retryControllersRef.current.clear();
    };
  }, []);

  useSingleFlightPolling({
    enabled: hasRunningPapers,
    identity: batchIdentity,
    intervalMs: 3500,
    poll: async (signal) => {
      const expectedIdentity = batchIdentity;
      const currentPapers = papersRef.current;
      try {
        const statuses = await Promise.all(currentPapers.map((paper) => getPaperStatus(paper.id, signal)));
        if (signal.aborted || getBatchIdentity(papersRef.current) !== expectedIdentity) {
          return;
        }
        const statusesById = new Map(statuses.map((status) => [status.id, status]));
        setPapers((current) => current.map((paper) => {
          const status = statusesById.get(paper.id);
          return status ? { ...paper, ...status } : paper;
        }));
      } catch (error) {
        if (!isAbortError(error) && getBatchIdentity(papersRef.current) === expectedIdentity) {
          setMessage(getErrorMessage(error));
        }
      }
    },
  });

  useEffect(() => {
    if (!allPapersReady || summary) {
      return;
    }
    const summaryKey = `${batchIdentity}:${goal}`;
    if (summaryStartedKeyRef.current === summaryKey) {
      return;
    }
    const revision = batchRevisionRef.current;
    const currentPapers = [...papers];
    let controller: AbortController | null = null;
    const timeoutId = window.setTimeout(() => {
      if (getBatchIdentity(papersRef.current) !== batchIdentity) {
        return;
      }
      summaryStartedKeyRef.current = summaryKey;
      controller = new AbortController();
      summaryControllerRef.current = controller;
      void runBatchSummary(currentPapers, controller, revision);
    }, 0);
    return () => {
      window.clearTimeout(timeoutId);
      controller?.abort();
    };
  }, [allPapersReady, batchIdentity, goal, summary]);

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const input = event.currentTarget.elements.namedItem("files") as HTMLInputElement | null;
    const files = Array.from(input?.files ?? []);
    if (!files.length) {
      setMessage("Choose at least one PDF.");
      return;
    }

    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));

    batchRevisionRef.current += 1;
    uploadControllerRef.current?.abort();
    summaryControllerRef.current?.abort();
    retryControllersRef.current.forEach((controller) => controller.abort());
    retryControllersRef.current.clear();
    const revision = batchRevisionRef.current;
    const controller = new AbortController();
    uploadControllerRef.current = controller;
    summaryStartedKeyRef.current = null;
    setUploading(true);
    setMessage(null);
    setSummary(null);
    setPapers([]);
    setRetryingIds(new Set());
    try {
      const response = await batchUploadPapers(formData, controller.signal);
      if (controller.signal.aborted || batchRevisionRef.current !== revision) {
        return;
      }
      setPapers(response.items.map((item) => item.paper));
    } catch (error) {
      if (!isAbortError(error) && batchRevisionRef.current === revision) {
        setMessage(getErrorMessage(error));
      }
    } finally {
      if (uploadControllerRef.current === controller) {
        uploadControllerRef.current = null;
        setUploading(false);
      }
    }
  }

  async function runBatchSummary(
    currentPapers: LibraryPaper[],
    controller: AbortController,
    revision: number,
  ) {
    setSummarizing(true);
    setMessage(null);
    try {
      const nextSummary = await createBatchSummary(currentPapers.map((paper) => paper.id), goal, controller.signal);
      if (controller.signal.aborted || batchRevisionRef.current !== revision) {
        return;
      }
      setSummary(nextSummary);
    } catch (error) {
      if (!isAbortError(error) && batchRevisionRef.current === revision) {
        summaryStartedKeyRef.current = null;
        setMessage(getErrorMessage(error));
      }
    } finally {
      if (summaryControllerRef.current === controller) {
        summaryControllerRef.current = null;
        setSummarizing(false);
      }
    }
  }

  async function retryPaperAnalysis(paperId: string) {
    setRetryingIds((current) => new Set(current).add(paperId));
    setMessage(null);
    setSummary(null);
    summaryStartedKeyRef.current = null;
    retryControllersRef.current.get(paperId)?.abort();
    const controller = new AbortController();
    retryControllersRef.current.set(paperId, controller);
    const revision = batchRevisionRef.current;
    try {
      await analyzePaper(paperId, controller.signal);
      const status = await getPaperStatus(paperId, controller.signal);
      if (controller.signal.aborted || batchRevisionRef.current !== revision) {
        return;
      }
      setPapers((current) => current.map((paper) => (paper.id === paperId ? { ...paper, ...status } : paper)));
    } catch (error) {
      if (!isAbortError(error) && batchRevisionRef.current === revision) {
        setMessage(getErrorMessage(error));
      }
    } finally {
      if (retryControllersRef.current.get(paperId) === controller) {
        retryControllersRef.current.delete(paperId);
        setRetryingIds((current) => {
          const next = new Set(current);
          next.delete(paperId);
          return next;
        });
      }
    }
  }

  function exportCsv() {
    if (!summary) {
      return;
    }
    const rows = [
      ["Paper", "Main idea", "Problem / hypothesis", "Experiments", "Models / datasets", "Results", "Conclusions"],
      ...summary.papers.map((paper) => [
        paper.title,
        paper.main_idea,
        paper.problem_or_hypothesis,
        paper.experiments,
        paper.models_and_datasets,
        paper.results,
        paper.conclusions,
      ]),
    ];
    const csv = rows.map((row) => row.map(csvCell).join(",")).join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "research-macha-batch-summary.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="batch-workspace">
      <PageHeader
        eyebrow="Compare papers"
        title="Build a research matrix from a collection of PDFs."
        description="Compare research questions, methods, experiments, evidence, and conclusions without losing paper identity."
      />

      <Surface className="batch-upload-panel">
        <form className="batch-upload-form" onSubmit={handleUpload}>
          <Field label="PDF collection" htmlFor="batch-files" hint="Choose up to 10 PDFs. The batch is created only after every file passes validation.">
            <input id="batch-files" name="files" type="file" accept="application/pdf" multiple />
          </Field>
          <Field label="Comparison goal" htmlFor="batch-goal" hint="Describe what should be emphasized across every paper.">
            <input id="batch-goal" value={goal} onChange={(event) => setGoal(event.target.value)} />
          </Field>
          <ActionButton type="submit" busy={uploading} busyLabel="Uploading papers...">Upload and compare</ActionButton>
        </form>
      </Surface>

      {message ? <Alert tone="warning" title="Comparison status"><p>{message}</p></Alert> : null}
      {uploading ? <Alert tone="info" title="Preparing the batch"><p>Validating PDFs and creating analysis jobs...</p></Alert> : null}
      {!papers.length && !uploading ? (
        <Surface>
          <EmptyState
            title="No comparison loaded"
            description="Add multiple PDFs to build a dimension-by-dimension research matrix. Each paper remains linked to its reader workspace."
          />
        </Surface>
      ) : null}

      {papers.length ? (
        <Surface className="batch-analysis-panel">
          <div className="batch-section-heading">
            <div>
              <p>Analysis</p>
              <h2>Uploaded papers</h2>
            </div>
            {summarizing ? <StatusBadge status="processing" label="Building comparison" /> : null}
          </div>
          <BatchStats papers={papers} />
          {failedPaperCount ? (
            <Alert tone="danger" title={`${failedPaperCount} ${failedPaperCount === 1 ? "paper needs" : "papers need"} attention`}>
              <p>Retry failed analysis before the comparison can be generated.</p>
            </Alert>
          ) : null}
          <div className="batch-paper-list">
            {papers.map((paper) => (
              <div className="batch-paper-entry" key={paper.id}>
                <div className="paper-status-row">
                  <Link to={`/reader/${paper.id}`}>{paper.title}</Link>
                  <div className="paper-row-actions">
                    <StatusBadge status={paper.status} />
                    {paper.status === "failed" || paper.status === "degraded" || paper.analysis_warning ? (
                      <ActionButton
                        type="button"
                        variant="secondary"
                        size="compact"
                        onClick={() => void retryPaperAnalysis(paper.id)}
                        busy={retryingIds.has(paper.id)}
                        busyLabel="Retrying..."
                      >
                        Retry
                      </ActionButton>
                    ) : null}
                  </div>
                </div>
                {paper.status === "degraded" || paper.analysis_warning ? (
                  <GenerationNotice mode={paper.analysis_mode} warnings={paper.analysis_warning} label="Paper analysis warning" />
                ) : null}
              </div>
            ))}
          </div>
        </Surface>
      ) : null}

      {summary ? (
        <Surface className="batch-comparison-panel">
          <div className="batch-section-heading">
            <div>
              <p>Cross-paper synthesis</p>
              <h2>Comparison matrix</h2>
            </div>
            <ActionButton type="button" variant="secondary" size="compact" onClick={exportCsv}>Export CSV</ActionButton>
          </div>
          <GenerationNotice mode={summary.generation_mode} warnings={summary.warnings} />
          <section className="batch-takeaway" aria-labelledby="batch-takeaway-title">
            <h3 id="batch-takeaway-title">Overall takeaway</h3>
            <p>{summary.overall_takeaway}</p>
          </section>
          <div className="batch-matrix-scroll">
            <table className="batch-matrix" aria-label="Paper comparison matrix">
              <thead>
                <tr>
                  <th scope="col">Dimension</th>
                  {summary.papers.map((paper) => (
                    <th scope="col" key={paper.paper_id}>
                      <Link to={`/reader/${paper.paper_id}`}>{paper.title}</Link>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {comparisonDimensions.map((dimension) => (
                  <tr key={dimension.key}>
                    <th scope="row">{dimension.label}</th>
                    {summary.papers.map((paper) => (
                      <td key={`${dimension.key}:${paper.paper_id}`}>{paper[dimension.key]}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Surface>
      ) : null}
    </div>
  );
}

function csvCell(value: string) {
  return `"${value.replace(/"/g, '""')}"`;
}

function BatchStats({ papers }: { papers: LibraryPaper[] }) {
  const ready = papers.filter((paper) => ["ready", "degraded"].includes(paper.status)).length;
  const failed = papers.filter((paper) => paper.status === "failed").length;
  const running = papers.length - ready - failed;
  return (
    <div className="batch-stats" aria-live="polite">
      <span>
        <strong>{papers.length}</strong>
        uploaded
      </span>
      <span>
        <strong>{running}</strong>
        running
      </span>
      <span>
        <strong>{ready}</strong>
        ready
      </span>
      <span>
        <strong>{failed}</strong>
        failed
      </span>
    </div>
  );
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong.";
}

function getBatchIdentity(papers: LibraryPaper[]) {
  return papers.map((paper) => paper.id).join(":");
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
