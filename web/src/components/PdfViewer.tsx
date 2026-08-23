import { useEffect, useRef, useState } from "react";

import * as pdfjsLib from "pdfjs-dist";
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.mjs?url";

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

type PdfDocument = Awaited<ReturnType<typeof pdfjsLib.getDocument>["promise"]>;

interface PdfViewerProps {
  title: string;
  url: string;
  targetPage?: number | null;
  onPageChange?: (page: number) => void;
}

export function PdfViewer({ title, url, targetPage, onPageChange }: PdfViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [document, setDocument] = useState<PdfDocument | null>(null);
  const [pageCount, setPageCount] = useState(0);
  const [pageNumber, setPageNumber] = useState(1);
  const [scale, setScale] = useState(1.15);
  const [loadingState, setLoadingState] = useState<"loading" | "ready" | "failed">("loading");
  const [rendering, setRendering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const loadingTask = pdfjsLib.getDocument({ url });

    setDocument(null);
    setPageCount(0);
    setPageNumber(1);
    setLoadingState("loading");
    setError(null);

    loadingTask.promise
      .then((nextDocument) => {
        if (cancelled) {
          return;
        }
        setDocument(nextDocument);
        setPageCount(nextDocument.numPages);
        setLoadingState("ready");
      })
      .catch((nextError: unknown) => {
        if (cancelled) {
          return;
        }
        setLoadingState("failed");
        setError(nextError instanceof Error ? nextError.message : "Could not load this PDF.");
      });

    return () => {
      cancelled = true;
      void loadingTask.destroy();
    };
  }, [url, reloadNonce]);

  useEffect(() => {
    if (!targetPage || !pageCount) {
      return;
    }
    setPageNumber(clampPage(targetPage, pageCount));
  }, [targetPage, pageCount]);

  useEffect(() => {
    onPageChange?.(pageNumber);
  }, [onPageChange, pageNumber]);

  useEffect(() => {
    if (!document || !canvasRef.current) {
      return;
    }

    let cancelled = false;
    const currentDocument = document;
    let renderTask: { cancel: () => void; promise: Promise<unknown> } | null = null;

    async function renderPage() {
      setRendering(true);
      try {
        const page = await currentDocument.getPage(pageNumber);
        if (cancelled || !canvasRef.current) {
          return;
        }

        const viewport = page.getViewport({ scale });
        const canvas = canvasRef.current;
        const context = canvas.getContext("2d");
        if (!context) {
          throw new Error("Canvas rendering is unavailable in this browser.");
        }

        const outputScale = window.devicePixelRatio || 1;
        canvas.width = Math.floor(viewport.width * outputScale);
        canvas.height = Math.floor(viewport.height * outputScale);
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;

        renderTask = page.render({
          canvas,
          canvasContext: context,
          viewport,
          transform: outputScale !== 1 ? [outputScale, 0, 0, outputScale, 0, 0] : undefined,
        });
        await renderTask.promise;
      } catch (nextError) {
        if (!cancelled && !isRenderCancelled(nextError)) {
          setLoadingState("failed");
          setError(nextError instanceof Error ? nextError.message : "Could not render this page.");
        }
      } finally {
        if (!cancelled) {
          setRendering(false);
        }
      }
    }

    void renderPage();

    return () => {
      cancelled = true;
      renderTask?.cancel();
    };
  }, [document, pageNumber, scale]);

  function goToPage(nextPage: number) {
    if (!pageCount) {
      return;
    }
    setPageNumber(clampPage(nextPage, pageCount));
  }

  function changeScale(delta: number) {
    setScale((current) => Math.min(2.4, Math.max(0.65, Number((current + delta).toFixed(2)))));
  }

  if (loadingState === "loading") {
    return (
      <div className="pdf-viewer-state">
        <span className="loader-ring" />
        <p>Loading PDF.js reader...</p>
      </div>
    );
  }

  if (loadingState === "failed") {
    return (
      <div className="pdf-viewer-state pdf-viewer-error">
        <p>{error ?? "Could not load this PDF."}</p>
        <button type="button" onClick={() => setReloadNonce((current) => current + 1)}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="pdf-viewer" aria-label={`PDF reader for ${title}`}>
      <div className="pdf-toolbar">
        <div className="pdf-page-controls">
          <button type="button" onClick={() => goToPage(pageNumber - 1)} disabled={pageNumber <= 1}>
            Prev
          </button>
          <label>
            <span>Page</span>
            <input
              aria-label="Current page"
              className="pdf-page-input"
              min={1}
              max={pageCount}
              type="number"
              value={pageNumber}
              onChange={(event) => goToPage(Number(event.target.value))}
            />
            <span>of {pageCount}</span>
          </label>
          <button type="button" onClick={() => goToPage(pageNumber + 1)} disabled={pageNumber >= pageCount}>
            Next
          </button>
        </div>
        <div className="pdf-zoom-controls">
          <button type="button" onClick={() => changeScale(-0.15)} disabled={scale <= 0.65}>
            -
          </button>
          <span>{Math.round(scale * 100)}%</span>
          <button type="button" onClick={() => changeScale(0.15)} disabled={scale >= 2.4}>
            +
          </button>
        </div>
      </div>
      <div className="pdf-canvas-shell">
        {rendering ? <span className="pdf-rendering-pill">Rendering page...</span> : null}
        <canvas ref={canvasRef} />
      </div>
    </div>
  );
}

function clampPage(page: number, pageCount: number) {
  if (!Number.isFinite(page)) {
    return 1;
  }
  return Math.min(pageCount, Math.max(1, Math.round(page)));
}

function isRenderCancelled(error: unknown) {
  return error instanceof Error && error.name === "RenderingCancelledException";
}
