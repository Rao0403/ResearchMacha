import { FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { GenerationNotice } from "../components/GenerationNotice";
import { useSingleFlightPolling } from "../hooks/useSingleFlightPolling";
import { analyzePaper, batchUploadPapers, createBatchSummary, getPaperStatus } from "../lib/api";
import type { BatchSummaryResponse, LibraryPaper } from "../types";

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
    <div className="mvp-page batch-page">
      <section className="mvp-header batch-hero">
        <div>
          <p className="eyebrow">PDF batch summary</p>
          <h2>Turn a folder of papers into a comparison table.</h2>
          <p>Upload multiple PDFs, let the analysis jobs finish, then export a concise research matrix.</p>
        </div>
      </section>

      <form className="batch-upload batch-console" onSubmit={handleUpload}>
        <label>
          <span>PDF collection</span>
          <input name="files" type="file" accept="application/pdf" multiple />
        </label>
        <label>
          <span>Summary goal</span>
          <input value={goal} onChange={(event) => setGoal(event.target.value)} aria-label="Batch summary goal" />
        </label>
        <button type="submit" disabled={uploading}>{uploading ? "Uploading..." : "Upload and summarize"}</button>
      </form>

      {message ? <p className="status-note">{message}</p> : null}
      {uploading ? <p className="status-note state-note-active">Uploading PDFs and creating analysis jobs...</p> : null}
      {!papers.length && !uploading ? (
        <section className="mvp-panel compact-empty-state">
          <p>No batch loaded yet. Add multiple PDFs to generate a paper-by-paper comparison table.</p>
        </section>
      ) : null}

      {papers.length ? (
        <section className="mvp-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Analysis</p>
              <h3>Uploaded papers</h3>
            </div>
            {summarizing ? <span className="status-pill status-processing">summarizing</span> : null}
          </div>
          <BatchStats papers={papers} />
          <div className="simple-list">
            {papers.map((paper) => (
              <div className="batch-paper-entry" key={paper.id}>
                <div className="paper-status-row">
                  <Link to={`/reader/${paper.id}`}>{paper.title}</Link>
                  <div className="paper-row-actions">
                    <span className={`status-pill status-${paper.status}`}>{paper.status}</span>
                    {paper.status === "failed" || paper.status === "degraded" || paper.analysis_warning ? (
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => void retryPaperAnalysis(paper.id)}
                        disabled={retryingIds.has(paper.id)}
                      >
                        {retryingIds.has(paper.id) ? "Retrying..." : "Retry"}
                      </button>
                    ) : null}
                  </div>
                </div>
                {paper.status === "degraded" || paper.analysis_warning ? (
                  <GenerationNotice mode={paper.analysis_mode} warnings={paper.analysis_warning} label="Paper analysis warning" />
                ) : null}
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {summary ? (
        <section className="mvp-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Summary</p>
              <h3>Comparison table</h3>
            </div>
            <button type="button" className="secondary-button" onClick={exportCsv}>
              Export CSV
            </button>
          </div>
          <GenerationNotice mode={summary.generation_mode} warnings={summary.warnings} />
          <p className="brief-summary">{summary.overall_takeaway}</p>
          <div className="table-wrap">
            <table className="data-table summary-table">
              <thead>
                <tr>
                  <th>Paper</th>
                  <th>Main idea</th>
                  <th>Problem / hypothesis</th>
                  <th>Experiments</th>
                  <th>Models / datasets</th>
                  <th>Results</th>
                  <th>Conclusions</th>
                </tr>
              </thead>
              <tbody>
                {summary.papers.map((paper) => (
                  <tr key={paper.paper_id}>
                    <td className="summary-paper-cell">
                      <Link to={`/reader/${paper.paper_id}`}>{paper.title}</Link>
                    </td>
                    <td>{paper.main_idea}</td>
                    <td>{paper.problem_or_hypothesis}</td>
                    <td>{paper.experiments}</td>
                    <td>{paper.models_and_datasets}</td>
                    <td>{paper.results}</td>
                    <td>{paper.conclusions}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
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
    <div className="batch-stats">
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
