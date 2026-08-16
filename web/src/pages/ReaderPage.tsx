import { FormEvent, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { getPaper, getPaperSummary, getPdfUrl, sendChatMessage, uploadPaper } from "../lib/api";
import type { ChatMessage, Highlight, PaperDetail, PaperSummary, PaperSummaryResponse } from "../types";

type ReaderTab = "notes" | "highlights" | "chat";
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

export function ReaderPage() {
  const { paperId: routePaperId } = useParams();
  const [paperIdInput, setPaperIdInput] = useState(routePaperId ?? "");
  const [paper, setPaper] = useState<PaperDetail | null>(null);
  const [summaryPayload, setSummaryPayload] = useState<PaperSummaryResponse | null>(null);
  const [activeTab, setActiveTab] = useState<ReaderTab>("notes");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [question, setQuestion] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (routePaperId) {
      setPaperIdInput(routePaperId);
      void loadPaper(routePaperId);
    }
  }, [routePaperId]);

  useEffect(() => {
    if (!paper || paper.status === "ready" || paper.status === "failed") {
      return;
    }

    const interval = window.setInterval(() => {
      void loadPaper(paper.id, true);
    }, 3500);

    return () => window.clearInterval(interval);
  }, [paper]);

  async function loadPaper(paperId: string, quiet = false) {
    try {
      const nextPaper = await getPaper(paperId);
      setPaper(nextPaper);
      if (nextPaper.status === "ready") {
        await loadSummary(nextPaper.id);
      } else if (!quiet) {
        setMessage("Analysis is queued or running. Notes will appear when ready.");
      }
    } catch (error) {
      setMessage(getErrorMessage(error));
    }
  }

  async function loadSummary(paperId: string) {
    try {
      const payload = await getPaperSummary(paperId);
      setSummaryPayload(payload);
      setMessage(null);
    } catch {
      setSummaryPayload(null);
      setMessage("Analysis is still running. Notes will appear when ready.");
    }
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const input = form.elements.namedItem("file") as HTMLInputElement | null;
    const file = input?.files?.[0];
    if (!file) {
      setMessage("Choose a PDF first.");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);
    formData.append("title", file.name.replace(/\.pdf$/i, ""));

    setUploading(true);
    setMessage(null);
    try {
      const response = await uploadPaper(formData);
      setPaperIdInput(response.paper.id);
      await loadPaper(response.paper.id);
    } catch (error) {
      setMessage(getErrorMessage(error));
    } finally {
      setUploading(false);
    }
  }

  async function handleOpen(event: FormEvent) {
    event.preventDefault();
    if (!paperIdInput.trim()) {
      return;
    }
    await loadPaper(paperIdInput.trim());
  }

  async function handleChat(event: FormEvent) {
    event.preventDefault();
    if (!paper || !question.trim()) {
      return;
    }

    const pendingQuestion = question.trim();
    setQuestion("");
    setSending(true);
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

    try {
      const response = await sendChatMessage(paper.id, pendingQuestion, sessionId);
      setSessionId(response.session_id);
      setMessages((current) => [...current, response.answer]);
    } catch (error) {
      setMessage(getErrorMessage(error));
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="mvp-page reader-page">
      <section className="mvp-header">
        <p className="eyebrow">Paper reader</p>
        <h2>Read one paper with grounded notes, highlights, and chat.</h2>
      </section>

      <div className="reader-controls">
        <form onSubmit={handleUpload}>
          <input name="file" type="file" accept="application/pdf" />
          <button type="submit" disabled={uploading}>{uploading ? "Uploading..." : "Upload PDF"}</button>
        </form>
        <form onSubmit={handleOpen}>
          <input value={paperIdInput} onChange={(event) => setPaperIdInput(event.target.value)} placeholder="Open existing paper id" />
          <button type="submit">Open</button>
        </form>
      </div>

      {message ? <p className="status-note">{message}</p> : null}

      <div className="reader-grid">
        <section className="pdf-workspace">
          {paper ? (
            <>
              <div className="reader-title-row">
                <div>
                  <h3>{paper.title}</h3>
                  <p className="authors">{paper.authors.join(", ") || "Uploaded paper"}</p>
                </div>
                <div className="reader-actions">
                  <span className={`status-pill status-${paper.status}`}>{paper.status}</span>
                  <a href={getPdfUrl(paper.id)} target="_blank" rel="noreferrer">
                    Open PDF
                  </a>
                </div>
              </div>
              <iframe title={paper.title} src={getPdfUrl(paper.id)} className="pdf-frame" />
            </>
          ) : (
            <div className="empty-state">
              <p>Upload a PDF or open a saved paper id to start reading.</p>
            </div>
          )}
        </section>

        <aside className="reader-side-panel">
          <div className="tab-row">
            <button type="button" className={activeTab === "notes" ? "tab-active" : ""} onClick={() => setActiveTab("notes")}>
              Notes
            </button>
            <button type="button" className={activeTab === "highlights" ? "tab-active" : ""} onClick={() => setActiveTab("highlights")}>
              Highlights
            </button>
            <button type="button" className={activeTab === "chat" ? "tab-active" : ""} onClick={() => setActiveTab("chat")}>
              Chat
            </button>
          </div>

          {activeTab === "notes" ? <NotesPanel summary={summaryPayload?.summary ?? paper?.summary ?? null} /> : null}
          {activeTab === "highlights" ? <HighlightsPanel highlights={summaryPayload?.highlights ?? paper?.highlights ?? []} /> : null}
          {activeTab === "chat" ? (
            <ChatPanel
              disabled={!paper}
              messages={messages}
              question={question}
              sending={sending}
              onQuestionChange={setQuestion}
              onSubmit={handleChat}
            />
          ) : null}
        </aside>
      </div>
    </div>
  );
}

function NotesPanel({ summary }: { summary: PaperSummary | null }) {
  if (!summary) {
    return <p className="status-note">Notes are generated after paper analysis finishes.</p>;
  }

  return (
    <div className="notes-list">
      {summaryLabels.map(([key, label]) => (
        <section key={key}>
          <h4>{label}</h4>
          <p>{summary[key]}</p>
          <div className="citation-row">
            {(summary.section_citations[key] ?? []).map((citation, index) => (
              <span className="citation-chip" key={`${key}-${index}`}>
                p.{citation.page}
              </span>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function HighlightsPanel({ highlights }: { highlights: Highlight[] }) {
  if (!highlights.length) {
    return <p className="status-note">Highlights are generated after paper analysis finishes.</p>;
  }

  return (
    <div className="notes-list">
      {highlights.map((highlight) => (
        <section key={highlight.id}>
          <h4>{highlight.label}</h4>
          <p>{highlight.explanation}</p>
          {highlight.citations.map((citation, index) => (
            <blockquote key={`${highlight.id}-${index}`}>
              <strong>Page {citation.page}</strong>
              <span>{citation.excerpt}</span>
            </blockquote>
          ))}
        </section>
      ))}
    </div>
  );
}

function ChatPanel({
  disabled,
  messages,
  question,
  sending,
  onQuestionChange,
  onSubmit,
}: {
  disabled: boolean;
  messages: ChatMessage[];
  question: string;
  sending: boolean;
  onQuestionChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <div className="reader-chat">
      <div className="chat-thread">
        {messages.map((message) => (
          <article className={`chat-bubble chat-${message.role}`} key={message.id}>
            <p>{message.content}</p>
            <div className="citation-row">
              {message.citations.map((citation, index) => (
                <span className="citation-chip" key={`${message.id}-${index}`}>
                  p.{citation.page}
                </span>
              ))}
            </div>
          </article>
        ))}
        {!messages.length ? <p className="status-note">Ask about methods, assumptions, datasets, results, or limitations.</p> : null}
      </div>
      <form className="chat-form" onSubmit={onSubmit}>
        <textarea
          value={question}
          onChange={(event) => onQuestionChange(event.target.value)}
          placeholder="What should I pay attention to in the experiments?"
          rows={4}
          disabled={disabled}
        />
        <button type="submit" disabled={disabled || sending}>{sending ? "Asking..." : "Ask"}</button>
      </form>
    </div>
  );
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong.";
}
