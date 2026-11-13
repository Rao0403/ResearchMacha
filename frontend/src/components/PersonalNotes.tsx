import { FormEvent, useEffect, useRef, useState } from "react";
import { deletePersonalNote, listPersonalNotes, savePersonalNote } from "../lib/api";
import type { PersonalNote } from "../types";
import { ActionButton, Alert, Field } from "./ui";

interface Draft { id: string; body: string; page: number | null; excerpt: string; version?: number }
const blank = (): Draft => ({ id: crypto.randomUUID(), body: "", page: null, excerpt: "" });
const draftKey = (paperId: string) => `research-macha:note-draft:${paperId}`;
function restoreDraft(paperId: string): Draft {
  try {
    const value = JSON.parse(sessionStorage.getItem(draftKey(paperId)) ?? "null") as Draft | null;
    if (value && typeof value.id === "string" && typeof value.body === "string" && typeof value.excerpt === "string"
        && (value.page === null || Number.isInteger(value.page)) && (value.version === undefined || Number.isInteger(value.version))) return value;
  } catch { /* A fresh editor remains usable when browser storage is unavailable. */ }
  return blank();
}

export function PersonalNotes({ paperId, currentPage, selectedExcerpt, selectedPage, onPageClick }: {
  paperId: string; currentPage: number; selectedExcerpt?: string; selectedPage?: number; onPageClick: (page: number) => void;
}) {
  const [notes, setNotes] = useState<PersonalNote[]>([]);
  const [draft, setDraft] = useState<Draft>(() => restoreDraft(paperId));
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const [backupWarning, setBackupWarning] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const dirty = Boolean(draft.body || draft.excerpt || draft.version);

  useEffect(() => {
    try {
      if (dirty) sessionStorage.setItem(draftKey(paperId), JSON.stringify(draft));
      else sessionStorage.removeItem(draftKey(paperId));
      setBackupWarning("");
    } catch { setBackupWarning("Browser draft backup is unavailable. Save your note before leaving this screen."); }
  }, [paperId, draft, dirty]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  useEffect(() => {
    void load();
    return () => controllerRef.current?.abort();
  }, [paperId]);

  async function load() {
    controllerRef.current?.abort();
    const controller = new AbortController(); controllerRef.current = controller;
    setLoading(true); setError("");
    try {
      const data = await listPersonalNotes(paperId, controller.signal);
      if (!controller.signal.aborted) setNotes(data);
    } catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    finally { if (!controller.signal.aborted) setLoading(false); }
  }
  function edit(values: Partial<Draft>) { setDraft((value) => ({ ...value, ...values })); setSaved(""); }
  function discard() { setDraft(blank()); setError(""); setSaved(""); }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!draft.body.trim() || busy || loading) return;
    controllerRef.current?.abort();
    const controller = new AbortController(); controllerRef.current = controller;
    setBusy(true); setError(""); setSaved("");
    try {
      const note = await savePersonalNote(paperId, { ...draft, excerpt: draft.excerpt || null }, controller.signal);
      if (controller.signal.aborted) return;
      setNotes((rows) => [note, ...rows.filter((n) => n.id !== note.id)]);
      setDraft(blank()); setSaved("Note saved to your workspace.");
    } catch (e) { if (!controller.signal.aborted) setError(`${message(e)} Your draft is still here.`); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  async function remove(note: PersonalNote) {
    controllerRef.current?.abort();
    const controller = new AbortController(); controllerRef.current = controller;
    setBusy(true); setError(""); setSaved("");
    try {
      await deletePersonalNote(paperId, note, controller.signal);
      if (!controller.signal.aborted) { setNotes((rows) => rows.filter((n) => n.id !== note.id)); setConfirmDelete(null); setSaved("Note deleted."); }
    } catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }

  return <div className="personal-notes">
    <h2>My Notes</h2><p>Your own thinking, kept separately from generated notes. Reanalysis does not replace it.</p>
    {loading && <p role="status">Loading saved notes...</p>}
    {error && <Alert tone="danger" title="Notes need attention" role="alert"><p>{error}</p><p>Reloading saved notes keeps your draft. Copy your text or discard the draft before editing a saved version.</p>
      <ActionButton type="button" variant="secondary" disabled={busy} onClick={() => void load()}>Reload saved notes</ActionButton></Alert>}
    {backupWarning && <p role="alert">{backupWarning}</p>}
    {saved && <p role="status">{saved}</p>}
    <form className="personal-note-editor" onSubmit={save}>
      <h3>{draft.version ? "Edit personal note" : "New personal note"}</h3>
      <Field label="Your note" htmlFor="personal-note-body"><textarea id="personal-note-body" rows={5} value={draft.body} maxLength={20000} required disabled={busy} onChange={(e) => edit({ body: e.target.value })} /></Field>
      <Field label="Page (optional)" htmlFor="personal-note-page"><input id="personal-note-page" type="number" min={1} value={draft.page ?? ""} disabled={busy} onChange={(e) => edit({ page: e.target.value ? Number(e.target.value) : null })} /></Field>
      <ActionButton type="button" variant="ghost" disabled={busy} onClick={() => edit({ page: currentPage })}>Attach current page ({currentPage})</ActionButton>
      <Field label="Selected passage (optional)" htmlFor="personal-note-excerpt"><textarea id="personal-note-excerpt" rows={2} value={draft.excerpt} maxLength={4000} disabled={busy} onChange={(e) => edit({ excerpt: e.target.value })} /></Field>
      {selectedExcerpt && <ActionButton type="button" variant="secondary" disabled={busy} onClick={() => edit({ page: selectedPage ?? currentPage, excerpt: selectedExcerpt.slice(0,4000) })}>Use selected source passage</ActionButton>}
      <div className="paper-row-actions"><ActionButton type="submit" busy={busy} busyLabel="Saving..." disabled={!draft.body.trim() || loading}>Save note</ActionButton>
        {dirty && <ActionButton type="button" variant="ghost" disabled={busy} onClick={discard}>Discard draft</ActionButton>}</div>
      {dirty && !backupWarning && <p role="status">Unsaved draft — kept in this browser tab until you save or discard it.</p>}
    </form>
    {!loading && notes.length === 0 && <p>No personal notes saved yet.</p>}
    {notes.map((note) => <article className="personal-note" key={note.id}>
      <p className="personal-note-body">{note.body}</p>
      {note.excerpt && <blockquote>{note.excerpt}</blockquote>}
      {note.page && <button type="button" className="reader-citation-chip" onClick={() => onPageClick(note.page!)}>p.{note.page}</button>}
      <small>Saved {new Date(note.updated_at).toLocaleString()}</small>
      <div className="paper-row-actions"><ActionButton type="button" variant="secondary" disabled={dirty || busy} onClick={() => { setDraft({ id:note.id,body:note.body,page:note.page,excerpt:note.excerpt ?? "",version:note.version }); setSaved(""); }}>Edit note</ActionButton>
        <ActionButton type="button" variant="ghost" disabled={busy || (dirty && draft.id===note.id)} onClick={() => setConfirmDelete(note.id)}>Delete note</ActionButton></div>
      {confirmDelete===note.id && <div><p>Delete this personal note permanently?</p><ActionButton type="button" variant="danger" disabled={busy} onClick={() => void remove(note)}>Confirm delete</ActionButton>
        <ActionButton type="button" variant="ghost" disabled={busy} onClick={() => setConfirmDelete(null)}>Keep note</ActionButton></div>}
    </article>)}
  </div>;
}

function message(error: unknown) { return error instanceof Error ? error.message : "Notes are unavailable."; }
