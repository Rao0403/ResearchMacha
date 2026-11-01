import { FormEvent, useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { GenerationNotice } from "../components/GenerationNotice";
import { PdfViewer } from "../components/PdfViewer";
import { ActionButton, Alert, EmptyState, PageHeader, StatusBadge, Tabs } from "../components/ui";
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
  const [searchParams] = useSearchParams();
  const requestedPage = parsePageNumber(searchParams.get("page"));
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
      openPaper(routePaperId, requestedPage);
    }
  }, [routePaperId, requestedPage]);

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

  function openPaper(paperId: string, initialPage?: number | null) {
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
      setCurrentPage(initialPage ?? 1);
      setTargetPage(initialPage ?? null);
    } else if (initialPage) {
      setTargetPage(initialPage);
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

  const visibleSummary = summaryPayload?.summary ?? paper?.summary ?? null;
  const visibleHighlights = summaryPayload?.highlights ?? paper?.highlights ?? [];
  const readerTabs = [
    {
      id: "notes",
      label: "AI Notes",
      content: <NotesPanel summary={visibleSummary} onCitationClick={jumpToCitation} />,
    },
    {
      id: "highlights",
      label: `Highlights${visibleHighlights.length ? ` (${visibleHighlights.length})` : ""}`,
      content: <HighlightsPanel highlights={visibleHighlights} onCitationClick={jumpToCitation} />,
    },
    {
      id: "chat",
      label: "Chat",
      content: (
        <ChatPanel
          disabled={!paper}
          messages={messages}
          question={question}
          sending={sending}
          onQuestionChange={setQuestion}
          onSubmit={handleChat}
          onCitationClick={jumpToCitation}
        />
      ),
    },
  ];

  return (
    <div className="reader-workspace">
      <PageHeader
        eyebrow="Paper reader"
        title={paper?.title ?? "Read, question, and trace every claim to the PDF."}
        description={paper
          ? paper.authors.join(", ") || "Uploaded paper"
          : "Upload a paper or open one from your library to generate cited notes and ask grounded questions."}
        actions={paper ? (
          <>
            <span className="reader-page-indicator">Page {currentPage}</span>
            <StatusBadge status={paper.status} />
            {paper.status === "failed" || paper.status === "degraded" || paper.analysis_warning ? (
              <ActionButton
                type="button"
                variant="secondary"
                size="compact"
                onClick={() => void handleRetryAnalysis()}
                busy={retrying}
                busyLabel="Retrying..."
              >Retry analysis</ActionButton>
            ) : null}
            <a className="ui-button ui-button-secondary ui-button-compact" href={getPdfUrl(paper.id)} target="_blank" rel="noreferrer">
              Open PDF
            </a>
          </>
        ) : undefined}
      />

      <details className="reader-source-panel" open={!paper}>
        <summary>{paper ? "Open another paper" : "Add a paper"}</summary>
        <div className="reader-source-forms">
          <form onSubmit={handleUpload}>
            <label htmlFor="reader-upload">Upload a PDF</label>
            <input id="reader-upload" name="file" type="file" accept="application/pdf" />
            <ActionButton type="submit" busy={uploading} busyLabel="Uploading...">Upload PDF</ActionButton>
          </form>
          <span aria-hidden="true">or</span>
          <form onSubmit={handleOpen}>
            <label htmlFor="reader-paper-id">Open by paper ID</label>
            <input
              id="reader-paper-id"
              value={paperIdInput}
              onChange={(event) => setPaperIdInput(event.target.value)}
              placeholder="Paste paper ID"
            />
            <ActionButton type="submit" variant="secondary">Open</ActionButton>
          </form>
        </div>
      </details>

      {message ? <Alert tone={paper && !["ready", "degraded", "failed"].includes(paper.status) ? "info" : "warning"} title="Reader status"><p>{message}</p></Alert> : null}

      {paper?.analysis_warning ? (
        <GenerationNotice mode={paper.analysis_mode} warnings={paper.analysis_warning} label="Paper analysis warning" />
      ) : null}

      <div className="reader-grid">
        <section className="pdf-workspace" ref={pdfSectionRef}>
          {paper ? (
            <PdfViewer title={paper.title} url={getPdfUrl(paper.id)} targetPage={targetPage} onPageChange={setCurrentPage} />
          ) : (
            <EmptyState
              title="No paper open"
              description="Upload a PDF or open a saved paper ID to start reading. Processing runs in the background and this workspace updates automatically."
            />
          )}
        </section>

        <aside className="reader-side-panel" aria-label="Paper notes and chat">
          <Tabs
            label="Paper workspace views"
            items={readerTabs}
            value={activeTab}
            onValueChange={(value) => setActiveTab(value as ReaderTab)}
          />
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
      <GenerationNotice mode={summary.generation_mode} warnings={summary.warning} />
      {summaryLabels.map(([key, label], sectionIndex) => (
        <section className="reader-note-section" key={key}>
          <span className="reader-note-index">{String(sectionIndex + 1).padStart(2, "0")}</span>
          <div>
            <h2>{label}</h2>
            <p>{summary[key]}</p>
            <div className="citation-row">
              {(summary.section_citations[key] ?? []).map((citation, index) => (
                <CitationButton citation={citation} key={`${key}-${index}`} onClick={onCitationClick} />
              ))}
            </div>
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
        <section className="reader-highlight" key={highlight.id}>
          <h2>{highlight.label}</h2>
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
      <div className="chat-thread" aria-live="polite" aria-relevant="additions">
        {messages.map((message) => (
          <article className={`chat-bubble chat-${message.role}`} key={message.id}>
            {message.role === "assistant" ? (
              <GenerationNotice mode={message.generation_mode} warnings={message.warning} />
            ) : null}
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
        <label htmlFor="reader-chat-question">Ask about this paper</label>
        <textarea
          id="reader-chat-question"
          value={question}
          onChange={(event) => onQuestionChange(event.target.value)}
          placeholder="What should I pay attention to in the experiments?"
          rows={4}
          disabled={disabled}
        />
        <ActionButton type="submit" disabled={disabled} busy={sending} busyLabel="Asking...">Ask</ActionButton>
      </form>
    </div>
  );
}

function CitationButton({ citation, onClick }: { citation: { page: number; excerpt?: string }; onClick: (page: number) => void }) {
  return (
    <button
      type="button"
      className="reader-citation-chip"
      aria-label={`Jump to page ${citation.page}`}
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

function parsePageNumber(value: string | null) {
  if (!value) {
    return null;
  }
  const page = Number(value);
  return Number.isInteger(page) && page > 0 ? page : null;
}
