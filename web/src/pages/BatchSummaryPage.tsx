import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { analyzePaper, batchUploadPapers, createBatchSummary, getPaper } from "../lib/api";
import type { BatchSummaryResponse, LibraryPaper } from "../types";

export function BatchSummaryPage() {
  const [papers, setPapers] = useState<LibraryPaper[]>([]);
  const [summary, setSummary] = useState<BatchSummaryResponse | null>(null);
  const [goal, setGoal] = useState("Extract the main ideas, hypothesis, experiments, models, datasets, results, and conclusions.");
  const [uploading, setUploading] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
  const [retryingIds, setRetryingIds] = useState<Set<string>>(new Set());
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!papers.length) {
      return;
    }

    const hasRunningPapers = papers.some((paper) => !["ready", "failed"].includes(paper.status));
    if (!hasRunningPapers) {
      if (papers.every((paper) => paper.status === "ready") && !summary && !summarizing) {
        void runBatchSummary(papers);
      }
      return;
    }

    const interval = window.setInterval(async () => {
      try {
        const updated = await Promise.all(papers.map((paper) => getPaper(paper.id)));
        setPapers(updated);
      } catch (error) {
        setMessage(getErrorMessage(error));
      }
    }, 3500);

    return () => window.clearInterval(interval);
  }, [papers, summary, summarizing]);

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

    setUploading(true);
    setMessage(null);
    setSummary(null);
    try {
      const response = await batchUploadPapers(formData);
      setPapers(response.items.map((item) => item.paper));
    } catch (error) {
      setMessage(getErrorMessage(error));
    } finally {
      setUploading(false);
    }
  }

  async function runBatchSummary(currentPapers: LibraryPaper[]) {
    setSummarizing(true);
    setMessage(null);
    try {
      const nextSummary = await createBatchSummary(currentPapers.map((paper) => paper.id), goal);
      setSummary(nextSummary);
    } catch (error) {
      setMessage(getErrorMessage(error));
    } finally {
      setSummarizing(false);
    }
  }

  async function retryPaperAnalysis(paperId: string) {
    setRetryingIds((current) => new Set(current).add(paperId));
    setMessage(null);
    setSummary(null);
    try {
      await analyzePaper(paperId);
      const updated = await getPaper(paperId);
      setPapers((current) => current.map((paper) => (paper.id === paperId ? updated : paper)));
    } catch (error) {
      setMessage(getErrorMessage(error));
    } finally {
      setRetryingIds((current) => {
        const next = new Set(current);
        next.delete(paperId);
        return next;
      });
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
              <div className="paper-status-row" key={paper.id}>
                <Link to={`/reader/${paper.id}`}>{paper.title}</Link>
                <div className="paper-row-actions">
                  <span className={`status-pill status-${paper.status}`}>{paper.status}</span>
                  {paper.status === "failed" ? (
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
  const ready = papers.filter((paper) => paper.status === "ready").length;
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
