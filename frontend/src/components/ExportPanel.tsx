import { useEffect, useRef, useState } from "react";
import { downloadSavedWork, getExportOptions, type ExportKind, type ExportFormat, type ExportOptions } from "../lib/api";
import { ActionButton, Alert } from "./ui";

export function ExportPanel({ kind, id, revision }: { kind: ExportKind; id: string; revision?: string }) {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<ExportOptions | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [refresh, setRefresh] = useState(0);
  const downloadRef = useRef<AbortController | null>(null);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setOptions(null); setError("");
    getExportOptions(kind, id, controller.signal).then((data) => { if (!controller.signal.aborted) {
      setOptions(data); setSelected((values) => values.filter((value) => data.notes.some((note) => note.id === value)));
    } })
      .catch((e: unknown) => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [kind, id, open, revision, refresh]);
  useEffect(() => () => downloadRef.current?.abort(), [kind, id]);

  async function download(format: ExportFormat) {
    downloadRef.current?.abort();
    const controller = new AbortController(); downloadRef.current = controller;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await downloadSavedWork(kind, id, format, selected, controller.signal);
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(result.blob);
      const link = document.createElement("a"); link.href = url; link.download = result.filename;
      document.body.append(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice("Download prepared from saved data. No model calls were made.");
    } catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }

  return <section className="workspace-export" aria-label="Export saved work">
    <ActionButton type="button" variant="secondary" size="compact" aria-expanded={open} onClick={() => setOpen(!open)}>Export</ActionButton>
    {open && <div className="workspace-export-content">
      <p>Download the saved result and its references. Local PDF links work in this installation.</p>
      {!options && !error && <p role="status">Loading export options...</p>}
      {error && <Alert tone="danger" title="Export unavailable" role="alert"><p>{error}</p></Alert>}
      <ActionButton type="button" variant="ghost" disabled={busy} onClick={() => setRefresh((value) => value+1)}>Refresh saved notes and options</ActionButton>
      {options && <>
        {options.warnings.length > 0 && <Alert tone="warning" title="Included in this export">{options.warnings.map((warning,i) => <p key={i}>{warning}</p>)}</Alert>}
        {!options.has_result && kind !== "paper" && <p>No completed result is saved yet. You can export references for the selected evidence.</p>}
        {options.notes.length > 0 && <fieldset className="export-note-selection"><legend>Include personal notes in Markdown</legend>
          <p>Only checked notes are included. These are your saved notes; unsaved drafts are not exported.</p>
          {options.notes.map((note) => <label key={note.id}><input type="checkbox" checked={selected.includes(note.id)}
            disabled={busy || (!selected.includes(note.id) && selected.length >= 100)} onChange={(e) => setSelected(e.target.checked ? [...selected,note.id] : selected.filter((value) => value !== note.id))} />
            <span><strong>{note.paper_title}{note.page ? ` · p.${note.page}` : ""}</strong><small>{note.preview}</small></span></label>)}
        </fieldset>}
        <div className="paper-row-actions">
          <ActionButton type="button" variant="secondary" busy={busy} disabled={!options.has_result && kind !== "paper"} onClick={() => void download("markdown")}>Download Markdown</ActionButton>
          <ActionButton type="button" variant="secondary" disabled={busy || options.paper_count === 0} onClick={() => void download("bibtex")}>Download BibTeX</ActionButton>
          {kind === "comparison" && <ActionButton type="button" variant="secondary" disabled={busy || !options.has_result} onClick={() => void download("csv")}>Download CSV</ActionButton>}
        </div>
      </>}
      {notice && <p role="status">{notice}</p>}
    </div>}
  </section>;
}

function message(error: unknown) { return error instanceof Error ? error.message : "Could not prepare the export."; }
