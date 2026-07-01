import { FormEvent, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { analyzePaper, getPaper, getPaperSummary, getPdfUrl, sendChatMessage } from "../lib/api";
import type { ChatMessage, PaperDetail, PaperSummary, PaperSummaryResponse } from "../types";

type SummarySectionKey =
  | "problem_or_hypothesis"
  | "approach"
  | "experiments"
  | "results"
  | "conclusion"
  | "limitations_or_notes";

const summaryLabels: Array<[SummarySectionKey, string]> = [
  ["problem_or_hypothesis", "Problem or hypothesis"],
  ["approach", "Approach"],
  ["experiments", "Experiments"],
  ["results", "Results"],
  ["conclusion", "Conclusion"],
  ["limitations_or_notes", "Limitations and notes"],
];

export function PaperWorkspacePage() {
  const { paperId = "" } = useParams();
  const [paper, setPaper] = useState<PaperDetail | null>(null);
  const [summaryPayload, setSummaryPayload] = useState<PaperSummaryResponse | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [question, setQuestion] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [loadingSummary, setLoadingSummary] = useState(true);
  const [sendingMessage, setSendingMessage] = useState(false);

  useEffect(() => {
    void loadPaper();
    void loadSummary();
  }, [paperId]);

  async function loadPaper() {
    try {
      const nextPaper = await getPaper(paperId);
      setPaper(nextPaper);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Failed to load paper.");
    }
  }

  async function loadSummary() {
    setLoadingSummary(true);
    try {
      const payload = await getPaperSummary(paperId);
      setSummaryPayload(payload);
      setStatus(null);
    } catch (error) {
      setSummaryPayload(null);
      setStatus(error instanceof Error ? error.message : "Summary is not available yet.");
    } finally {
      setLoadingSummary(false);
    }
  }

  async function handleReanalyze() {
    try {
      const job = await analyzePaper(paperId);
      setStatus(`Queued analysis job ${job.id}. Refresh notes after the job completes.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Failed to queue analysis.");
    }
  }

  async function handleSend(event: FormEvent) {
    event.preventDefault();
    if (!question.trim()) {
      return;
    }

    const pendingQuestion = question;
    setSendingMessage(true);
    setMessages((current) => [
      ...current,
      {
        id: `local-${Date.now()}`,
        role: "user",
        content: pendingQuestion,
        citations: [],
        created_at: new Date().toISOString(),
      },
    ]);
    setQuestion("");

    try {
      const response = await sendChatMessage(paperId, pendingQuestion, sessionId);
      setSessionId(response.session_id);
      setMessages((current) => [...current, response.answer]);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Failed to send question.");
    } finally {
      setSendingMessage(false);
    }
  }

  return (
    <div className="workspace-page">
      <section className="workspace-header panel">
        <div>
          <p className="eyebrow">Paper workspace</p>
          <h2>{paper?.title ?? "Loading paper..."}</h2>
          <p className="authors">{paper?.authors.join(", ") || "Authors unavailable"}</p>
        </div>
        <div className="workspace-actions">
          <span className={`status-pill status-${paper?.status ?? "pending"}`}>{paper?.status ?? "pending"}</span>
          <button type="button" onClick={() => void loadSummary()}>
            Refresh notes
          </button>
          <button type="button" onClick={() => void handleReanalyze()}>
            Re-analyze
          </button>
        </div>
      </section>

      {status ? <p className="status-note">{status}</p> : null}

      <div className="workspace-grid">
        <section className="panel pdf-panel">
          <div className="section-header">
            <div>
              <p className="eyebrow">Source</p>
              <h3>PDF and metadata</h3>
            </div>
          </div>
          {paper ? (
            <iframe title={paper.title} src={getPdfUrl(paper.id)} className="pdf-frame" />
          ) : (
            <div className="empty-card">
              <p>Loading PDF...</p>
            </div>
          )}
        </section>

        <section className="workspace-stack">
          <div className="panel">
            <div className="section-header">
              <div>
                <p className="eyebrow">Summary</p>
                <h3>Structured reading notes</h3>
              </div>
            </div>
            {loadingSummary ? (
              <p className="status-note">Loading summary...</p>
            ) : summaryPayload ? (
              <div className="summary-sections">
                {summaryLabels.map(([key, label]) => (
                  <article className="summary-card" key={key}>
                    <h4>{label}</h4>
                    <p>{summaryPayload.summary[key]}</p>
                    <div className="citation-row">
                      {(summaryPayload.summary.section_citations[key] ?? []).map((citation, index) => (
                        <span className="citation-chip" key={`${key}-${index}`}>
                          p.{citation.page}
                        </span>
                      ))}
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="empty-card">
                <p>The summary is not ready yet. Queue analysis or refresh this page.</p>
              </div>
            )}
          </div>

          <div className="panel">
            <div className="section-header">
              <div>
                <p className="eyebrow">Highlights</p>
                <h3>Important evidence</h3>
              </div>
            </div>
            <div className="highlight-list">
              {summaryPayload?.highlights.map((highlight) => (
                <article className="highlight-card" key={highlight.id}>
                  <h4>{highlight.label}</h4>
                  <p>{highlight.explanation}</p>
                  <div className="citation-column">
                    {highlight.citations.map((citation, index) => (
                      <div className="citation-block" key={`${highlight.id}-${index}`}>
                        <strong>Page {citation.page}</strong>
                        <span>{citation.excerpt}</span>
                      </div>
                    ))}
                  </div>
                </article>
              ))}
              {!summaryPayload?.highlights.length ? (
                <div className="empty-card">
                  <p>No highlights are available yet.</p>
                </div>
              ) : null}
            </div>
          </div>

          <div className="panel">
            <div className="section-header">
              <div>
                <p className="eyebrow">Paper chat</p>
                <h3>Ask focused questions</h3>
              </div>
            </div>
            <div className="chat-thread">
              {messages.map((message) => (
                <article className={`chat-bubble chat-${message.role}`} key={message.id}>
                  <p>{message.content}</p>
                  {message.citations.length ? (
                    <div className="citation-row">
                      {message.citations.map((citation, index) => (
                        <span className="citation-chip" key={`${message.id}-${index}`}>
                          p.{citation.page}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </article>
              ))}
              {messages.length === 0 ? (
                <div className="empty-card">
                  <p>Ask about the hypothesis, methods, experiments, or conclusions.</p>
                </div>
              ) : null}
            </div>
            <form className="chat-form" onSubmit={handleSend}>
              <textarea
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="What evidence supports the main conclusion?"
                rows={4}
              />
              <button type="submit" disabled={sendingMessage}>
                {sendingMessage ? "Sending..." : "Ask"}
              </button>
            </form>
          </div>
        </section>
      </div>
    </div>
  );
}
