import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { batchUploadPapers, createBatchSummary, getPaper } from "../lib/api";
import type { BatchSummaryResponse, LibraryPaper } from "../types";

export function BatchSummaryPage() {
  const [papers, setPapers] = useState<LibraryPaper[]>([]);
  const [summary, setSummary] = useState<BatchSummaryResponse | null>(null);
  const [goal, setGoal] = useState("Extract the main ideas, hypothesis, experiments, models, datasets, results, and conclusions.");
  const [uploading, setUploading] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
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

  return (
    <div className="mvp-page">
      <section className="mvp-header">
        <p className="eyebrow">PDF batch summary</p>
        <h2>Upload papers and get one compact comparison of what matters.</h2>
      </section>

      <form className="batch-upload" onSubmit={handleUpload}>
        <input name="files" type="file" accept="application/pdf" multiple />
        <input value={goal} onChange={(event) => setGoal(event.target.value)} aria-label="Batch summary goal" />
        <button type="submit" disabled={uploading}>{uploading ? "Uploading..." : "Upload and summarize"}</button>
      </form>

      {message ? <p className="status-note">{message}</p> : null}

      {papers.length ? (
        <section className="mvp-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Analysis</p>
              <h3>Uploaded papers</h3>
            </div>
            {summarizing ? <span className="status-pill status-processing">summarizing</span> : null}
          </div>
          <div className="simple-list">
            {papers.map((paper) => (
              <Link to={`/reader/${paper.id}`} className="paper-status-row" key={paper.id}>
                <span>{paper.title}</span>
                <span className={`status-pill status-${paper.status}`}>{paper.status}</span>
              </Link>
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
                    <td>{paper.title}</td>
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

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong.";
}
