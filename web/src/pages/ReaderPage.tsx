import { FormEvent, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { PdfViewer } from "../components/PdfViewer";
import { useSingleFlightPolling } from "../hooks/useSingleFlightPolling";
import { analyzePaper, getPaper, getPaperStatus, getPaperSummary, getPdfUrl, sendChatMessage, uploadPaper } from "../lib/api";
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
  const [retrying, setRetrying] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [targetPage, setTargetPage] = useState<number | null>(null);
  const pdfSectionRef = useRef<HTMLElement | null>(null);
  const activePaperIdRef = useRef<string | null>(null);
  const requestRevisionRef = useRef(0);
  const loadControllerRef = useRef<AbortController | null>(null);
  const chatControllerRef = useRef<AbortController | null>(null);
  const mutationControllerRef = useRef<AbortController | null>(null);
  const terminalLoadKeyRef = useRef<string | null>(null);

  useEffect(() => {
    if (routePaperId) {
      setPaperIdInput(routePaperId);
      openPaper(routePaperId);
    }
  }, [routePaperId]);

  useEffect(() => {
    return () => {
      requestRevisionRef.current += 1;
      loadControllerRef.current?.abort();
      chatControllerRef.current?.abort();
      mutationControllerRef.current?.abort();
    };
  }, []);

  const pollingEnabled = Boolean(paper && !["ready", "degraded", "failed"].includes(paper.status));
  useSingleFlightPolling({
    enabled: pollingEnabled,
    identity: paper?.id ?? "no-paper",
    intervalMs: 3500,
    poll: async (signal) => {
      if (!paper || activePaperIdRef.current !== paper.id) {
        return;
      }
      try {
        const nextStatus = await getPaperStatus(paper.id, signal);
        if (signal.aborted || activePaperIdRef.current !== nextStatus.id) {
          return;
        }
        if (["ready", "degraded"].includes(nextStatus.status)) {
          const terminalKey = `${nextStatus.id}:${nextStatus.analysis_generation}:${nextStatus.status}`;
          if (terminalLoadKeyRef.current !== terminalKey) {
            terminalLoadKeyRef.current = terminalKey;
            await refreshCompletedPaper(nextStatus.id, signal, requestRevisionRef.current);
          }
        } else {
          setPaper((current) => current?.id === nextStatus.id ? { ...current, ...nextStatus } : current);
        }
      } catch (error) {
        if (!isAbortError(error) && activePaperIdRef.current === paper.id) {
          setMessage(getErrorMessage(error));
        }
      }
    },
  });

  function openPaper(paperId: string) {
    const normalizedId = paperId.trim();
    if (!normalizedId) {
      return;
    }
    const identityChanged = activePaperIdRef.current !== normalizedId;
    requestRevisionRef.current += 1;
    const revision = requestRevisionRef.current;
    activePaperIdRef.current = normalizedId;
    terminalLoadKeyRef.current = null;
    loadControllerRef.current?.abort();
    chatControllerRef.current?.abort();
    mutationControllerRef.current?.abort();
    const controller = new AbortController();
    loadControllerRef.current = controller;
    if (identityChanged) {
      setPaper(null);
      setSummaryPayload(null);
      setMessages([]);
      setSessionId(undefined);
      setQuestion("");
      setCurrentPage(1);
      setTargetPage(null);
    }
    setMessage(null);
    setSending(false);
    void loadPaper(normalizedId, controller.signal, revision);
  }

  async function loadPaper(paperId: string, signal: AbortSignal, revision: number) {
    try {
      const nextPaper = await getPaper(paperId, signal);
      if (!isCurrentPaperRequest(paperId, signal, revision)) {
        return;
      }
      setPaper(nextPaper);
      if (["ready", "degraded"].includes(nextPaper.status)) {
        const terminalKey = `${nextPaper.id}:${nextPaper.analysis_generation}:${nextPaper.status}`;
        terminalLoadKeyRef.current = terminalKey;
        await loadSummary(nextPaper.id, signal, revision);
      } else {
        setMessage("Analysis is queued or running. Notes will appear when ready.");
      }
    } catch (error) {
      if (!isAbortError(error) && isCurrentPaperRequest(paperId, signal, revision)) {
        setMessage(getErrorMessage(error));
      }
    }
  }

  async function refreshCompletedPaper(paperId: string, signal: AbortSignal, revision: number) {
    try {
      const nextPaper = await getPaper(paperId, signal);
      if (!isCurrentPaperRequest(paperId, signal, revision)) {
        return;
      }
      const payload = await getPaperSummary(paperId, signal);
      if (!isCurrentPaperRequest(paperId, signal, revision)) {
        return;
      }
      setPaper(nextPaper);
      setSummaryPayload(payload);
      setMessage(null);
    } catch (error) {
      if (!isAbortError(error) && isCurrentPaperRequest(paperId, signal, revision)) {
        terminalLoadKeyRef.current = null;
        setMessage(getErrorMessage(error));
      }
    }
  }

  async function loadSummary(paperId: string, signal: AbortSignal, revision: number) {
    try {
      const payload = await getPaperSummary(paperId, signal);
      if (!isCurrentPaperRequest(paperId, signal, revision)) {
        return;
      }
      setSummaryPayload(payload);
      setMessage(null);
    } catch (error) {
      if (!isAbortError(error) && isCurrentPaperRequest(paperId, signal, revision)) {
        setSummaryPayload(null);
        setMessage("Analysis is still running. Notes will appear when ready.");
      }
    }
  }

  function isCurrentPaperRequest(paperId: string, signal: AbortSignal, revision: number) {
    return !signal.aborted && activePaperIdRef.current === paperId && requestRevisionRef.current === revision;
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

    mutationControllerRef.current?.abort();
    const controller = new AbortController();
    mutationControllerRef.current = controller;
    setUploading(true);
    setMessage(null);
    try {
      const response = await uploadPaper(formData, controller.signal);
      if (controller.signal.aborted) {
        return;
      }
      setPaperIdInput(response.paper.id);
      openPaper(response.paper.id);
    } catch (error) {
      if (!isAbortError(error)) {
        setMessage(getErrorMessage(error));
      }
    } finally {
      if (mutationControllerRef.current === controller) {
        mutationControllerRef.current = null;
        setUploading(false);
      }
    }
  }

  async function handleOpen(event: FormEvent) {
    event.preventDefault();
    if (!paperIdInput.trim()) {
      return;
    }
    openPaper(paperIdInput);
  }

  async function handleChat(event: FormEvent) {
    event.preventDefault();
    if (!paper || !question.trim()) {
      return;
    }

    const pendingQuestion = question.trim();
    const paperId = paper.id;
    const revision = requestRevisionRef.current;
    chatControllerRef.current?.abort();
    const controller = new AbortController();
    chatControllerRef.current = controller;
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
      const response = await sendChatMessage(paperId, pendingQuestion, sessionId, controller.signal);
      if (!isCurrentPaperRequest(paperId, controller.signal, revision)) {
        return;
      }
      setSessionId(response.session_id);
      setMessages((current) => [...current, response.answer]);
    } catch (error) {
      if (!isAbortError(error) && isCurrentPaperRequest(paperId, controller.signal, revision)) {
        setMessage(getErrorMessage(error));
      }
    } finally {
      if (chatControllerRef.current === controller) {
        chatControllerRef.current = null;
        setSending(false);
      }
    }
  }

  async function handleRetryAnalysis() {
    if (!paper) {
      return;
    }
    const paperId = paper.id;
    const revision = requestRevisionRef.current;
    mutationControllerRef.current?.abort();
    const controller = new AbortController();
    mutationControllerRef.current = controller;
    setRetrying(true);
    setMessage(null);
    try {
      await analyzePaper(paperId, controller.signal);
      if (!isCurrentPaperRequest(paperId, controller.signal, revision)) {
        return;
      }
      setPaper((current) => current?.id === paperId ? { ...current, status: "processing" } : current);
      setMessage("Analysis was requeued. Notes will refresh when ready.");
    } catch (error) {
      if (!isAbortError(error) && activePaperIdRef.current === paperId) {
        setMessage(getErrorMessage(error));
      }
    } finally {
      if (mutationControllerRef.current === controller) {
        mutationControllerRef.current = null;
        setRetrying(false);
      }
    }
  }

  function jumpToCitation(page: number) {
    setTargetPage(null);
    window.setTimeout(() => setTargetPage(page), 0);
    pdfSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <div className="mvp-page reader-page">
      <section className="mvp-header reader-hero">
        <div>
          <p className="eyebrow">Paper reader</p>
          <h2>Read the PDF. Follow the citations. Ask grounded questions.</h2>
        </div>
        {paper ? (
          <div className="reader-hero-meta">
            <span className={`status-pill status-${paper.status}`}>{paper.status}</span>
            <span>{paper.chunks.length} chunks</span>
            <span>{paper.highlights.length} highlights</span>
          </div>
        ) : null}
      </section>

      <div className="reader-controls reader-command-bar">
        <form onSubmit={handleUpload}>
          <label>
            <span>Upload a PDF</span>
            <input name="file" type="file" accept="application/pdf" />
          </label>
          <button type="submit" disabled={uploading}>{uploading ? "Uploading..." : "Upload PDF"}</button>
        </form>
        <form onSubmit={handleOpen}>
          <label>
            <span>Open existing paper</span>
            <input value={paperIdInput} onChange={(event) => setPaperIdInput(event.target.value)} placeholder="Paste paper id" />
          </label>
          <button type="submit">Open</button>
        </form>
      </div>

      {message ? <p className="status-note">{message}</p> : null}

      <div className="reader-grid">
        <section className="pdf-workspace" ref={pdfSectionRef}>
          {paper ? (
            <>
              <div className="reader-title-row reader-document-header">
                <div>
                  <h3>{paper.title}</h3>
                  <p className="authors">{paper.authors.join(", ") || "Uploaded paper"}</p>
                </div>
                <div className="reader-actions">
                  <span className="status-pill">page {currentPage}</span>
                  <span className={`status-pill status-${paper.status}`}>{paper.status}</span>
                  {paper.status === "failed" ? (
                    <button type="button" className="secondary-button" onClick={() => void handleRetryAnalysis()} disabled={retrying}>
                      {retrying ? "Retrying..." : "Retry analysis"}
                    </button>
                  ) : null}
                  <a href={getPdfUrl(paper.id)} target="_blank" rel="noreferrer">
                    Open PDF
                  </a>
                </div>
              </div>
              <PdfViewer title={paper.title} url={getPdfUrl(paper.id)} targetPage={targetPage} onPageChange={setCurrentPage} />
            </>
          ) : (
            <div className="empty-state">
              <p>Upload a PDF or open a saved paper id to start reading.</p>
            </div>
          )}
        </section>

        <aside className="reader-side-panel">
          <div className="tab-row reader-tabs">
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

          {activeTab === "notes" ? (
            <NotesPanel summary={summaryPayload?.summary ?? paper?.summary ?? null} onCitationClick={jumpToCitation} />
          ) : null}
          {activeTab === "highlights" ? (
            <HighlightsPanel highlights={summaryPayload?.highlights ?? paper?.highlights ?? []} onCitationClick={jumpToCitation} />
          ) : null}
          {activeTab === "chat" ? (
            <ChatPanel
              disabled={!paper}
              messages={messages}
              question={question}
              sending={sending}
              onQuestionChange={setQuestion}
              onSubmit={handleChat}
              onCitationClick={jumpToCitation}
            />
          ) : null}
        </aside>
      </div>
    </div>
  );
}

function NotesPanel({ summary, onCitationClick }: { summary: PaperSummary | null; onCitationClick: (page: number) => void }) {
  if (!summary) {
    return <p className="status-note reader-panel-empty">Notes are generated after paper analysis finishes.</p>;
  }

  return (
    <div className="notes-list">
      {summaryLabels.map(([key, label]) => (
        <section key={key}>
          <h4>{label}</h4>
          <p>{summary[key]}</p>
          <div className="citation-row">
            {(summary.section_citations[key] ?? []).map((citation, index) => (
              <CitationButton citation={citation} key={`${key}-${index}`} onClick={onCitationClick} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function HighlightsPanel({ highlights, onCitationClick }: { highlights: Highlight[]; onCitationClick: (page: number) => void }) {
  if (!highlights.length) {
    return <p className="status-note reader-panel-empty">Highlights are generated after paper analysis finishes.</p>;
  }

  return (
    <div className="notes-list">
      {highlights.map((highlight) => (
        <section key={highlight.id}>
          <h4>{highlight.label}</h4>
          <p>{highlight.explanation}</p>
          {highlight.citations.map((citation, index) => (
            <button
              type="button"
              className="highlight-citation-button"
              key={`${highlight.id}-${index}`}
              onClick={() => onCitationClick(citation.page)}
            >
              <strong>Page {citation.page}</strong>
              <span>{citation.excerpt}</span>
            </button>
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
  onCitationClick,
}: {
  disabled: boolean;
  messages: ChatMessage[];
  question: string;
  sending: boolean;
  onQuestionChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  onCitationClick: (page: number) => void;
}) {
  return (
    <div className="reader-chat">
      <div className="chat-thread">
        {messages.map((message) => (
          <article className={`chat-bubble chat-${message.role}`} key={message.id}>
            <p>{message.content}</p>
            <div className="citation-row">
              {message.citations.map((citation, index) => (
                <CitationButton citation={citation} key={`${message.id}-${index}`} onClick={onCitationClick} />
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

function CitationButton({ citation, onClick }: { citation: { page: number; excerpt?: string }; onClick: (page: number) => void }) {
  return (
    <button
      type="button"
      className="citation-chip citation-button"
      title={citation.excerpt ? `Jump to page ${citation.page}: ${citation.excerpt}` : `Jump to page ${citation.page}`}
      onClick={() => onClick(citation.page)}
    >
      p.{citation.page}
    </button>
  );
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong.";
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
