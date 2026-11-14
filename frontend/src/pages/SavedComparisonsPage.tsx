import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { GenerationNotice } from "../components/GenerationNotice";
import { LibraryPaperPicker } from "../components/LibraryPaperPicker";
import { SourcePassage } from "../components/SourcePassage";
import { ExportPanel } from "../components/ExportPanel";
import { ActionButton, Alert, EmptyState, Field, PageHeader, StatusBadge, Surface } from "../components/ui";
import { useSingleFlightPolling } from "../hooks/useSingleFlightPolling";
import { generateComparison, getComparison, getComparisonStatus, listComparisons, retryComparisonPaper, updateComparison, uploadComparison } from "../lib/api";
import type { BatchPaperSummary, BatchSummaryResponse, SavedComparison } from "../types";

const dimensions: Array<{ key: Exclude<keyof BatchPaperSummary, "paper_id" | "title" | "citations">; label: string }> = [
  { key: "main_idea", label: "Main idea" }, { key: "problem_or_hypothesis", label: "Problem / hypothesis" },
  { key: "experiments", label: "Experiments" }, { key: "models_and_datasets", label: "Models / datasets" },
  { key: "results", label: "Results" }, { key: "conclusions", label: "Conclusions" },
  { key: "limitations", label: "Limitations" }, { key: "comparability", label: "Evaluation conditions" },
];
const activeStatuses = ["waiting_for_papers", "queued", "running"];
const defaultGoal = "Compare the main ideas, methods, experiments, datasets, results, and conclusions.";

export function SavedComparisonsPage() {
  const { comparisonId } = useParams();
  const navigate = useNavigate();
  const [saved, setSaved] = useState<SavedComparison[]>([]);
  const [comparison, setComparison] = useState<SavedComparison | null>(null);
  const [name, setName] = useState("Paper comparison");
  const [goal, setGoal] = useState(defaultGoal);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [libraryIds, setLibraryIds] = useState<string[]>([]);
  const current = useRef(comparison);
  current.current = comparison;
  const loadController = useRef<AbortController | null>(null);
  const actionController = useRef<AbortController | null>(null);
  const uploadToken = useRef(crypto.randomUUID());
  const generationToken = useRef(crypto.randomUUID());
  const dirty = Boolean(comparison && (name !== comparison.name || goal !== comparison.goal || libraryIds.length > 0));

  useEffect(() => {
    if (comparisonId && current.current?.id === comparisonId) return;
    loadController.current?.abort(); actionController.current?.abort();
    const controller = new AbortController();
    loadController.current = controller;
    current.current = null; setComparison(null); setError(null); setLoading(true); setBusy(false); setLibraryIds([]);
    if (comparisonId) {
      getComparison(comparisonId, controller.signal).then((data) => {
        if (controller.signal.aborted) return;
        current.current = data; setComparison(data); setName(data.name); setGoal(data.goal);
      }).catch((e: unknown) => { if (!controller.signal.aborted) setError(message(e)); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    } else {
      setName("Paper comparison"); setGoal(defaultGoal); uploadToken.current = crypto.randomUUID();
      listComparisons(controller.signal).then((data) => { if (!controller.signal.aborted) setSaved(data); })
        .catch((e: unknown) => { if (!controller.signal.aborted) setError(message(e)); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }
    return () => controller.abort();
  }, [comparisonId]);
  useEffect(() => () => { loadController.current?.abort(); actionController.current?.abort(); }, []);

  useSingleFlightPolling({
    identity: comparison?.id ?? "no-comparison",
    enabled: Boolean(comparison && activeStatuses.includes(comparison.status)), intervalMs: 3500,
    poll: async (signal) => {
      const original = current.current;
      if (!original) return;
      try {
        const status = await getComparisonStatus(original.id, signal);
        if (signal.aborted || current.current?.id !== original.id) return;
        const readyCount = original.papers.filter((p) => ["ready", "degraded"].includes(p.status)).length;
        if (status.status !== original.status || status.updated_at !== original.updated_at || status.generation !== original.generation || status.ready_count !== readyCount) {
          const next = await getComparison(original.id, signal);
          if (!signal.aborted && current.current?.id === original.id) { current.current = next; setComparison(next); }
        }
      } catch (e) { if (!signal.aborted) setError(message(e)); }
    },
  });

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const input = event.currentTarget.elements.namedItem("files") as HTMLInputElement | null;
    const files = Array.from(input?.files ?? []);
    if (files.length + libraryIds.length < 2 || files.length + libraryIds.length > 10) { setError("Choose 2 to 10 papers across uploads and library."); return; }
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    form.set("name", name);
    form.set("goal", goal);
    form.set("request_id", uploadToken.current);
    form.set("library_paper_ids", JSON.stringify(libraryIds));
    const controller = new AbortController();
    actionController.current?.abort(); actionController.current = controller;
    setBusy(true); setError(null);
    try {
      const data = await uploadComparison(form, controller.signal);
      if (controller.signal.aborted) return;
      current.current = data; setComparison(data); setName(data.name); setGoal(data.goal);
      setLibraryIds([]);
      navigate(`/comparisons/${data.id}`);
    } catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    finally { if (actionController.current === controller) setBusy(false); }
  }

  async function action(kind: "save" | "generate" | "retry" | "remove", paperId?: string) {
    const original = current.current;
    if (!original) return;
    const controller = new AbortController();
    actionController.current?.abort(); actionController.current = controller;
    setBusy(true); setError(null);
    try {
      const data = kind === "generate" ? await generateComparison(original.id, original.version, generationToken.current, controller.signal)
        : kind === "retry" ? await retryComparisonPaper(original.id, paperId!, controller.signal)
        : await updateComparison(original.id, { name, goal, version: original.version, paper_ids: [...original.papers.filter((p) => kind !== "remove" || p.id !== paperId).map((p) => p.id), ...libraryIds] }, controller.signal);
      if (controller.signal.aborted || current.current?.id !== original.id) return;
      current.current = data; setComparison(data); setName(data.name); setGoal(data.goal);
      setLibraryIds([]);
      generationToken.current = crypto.randomUUID();
    } catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    finally { if (actionController.current === controller) setBusy(false); }
  }

  return <div className="batch-workspace">
    <PageHeader eyebrow="Compare papers" title={comparisonId ? "Saved paper comparison" : "Build a research matrix from a collection of PDFs."}
      description="Compare evidence and return to your saved results." actions={comparisonId ? <Link className="ui-button ui-button-secondary" to="/comparisons">All comparisons</Link> : undefined} />
    {error && <Alert tone="danger" title="Comparison needs attention" role="alert"><p>{error}</p></Alert>}
    {loading && <p role="status">Loading saved work...</p>}
    {!comparisonId && <Surface><form className="batch-upload-form" onSubmit={upload}>
      <Field label="Comparison name" htmlFor="comparison-name"><input id="comparison-name" name="name" value={name} maxLength={255} onChange={(e) => { setName(e.target.value); uploadToken.current = crypto.randomUUID(); }} required /></Field>
      <Field label="PDF collection" htmlFor="batch-files"><input id="batch-files" name="files" type="file" accept="application/pdf,.pdf" multiple onChange={() => { uploadToken.current = crypto.randomUUID(); }} /></Field>
      <LibraryPaperPicker selected={libraryIds} onChange={(ids) => { setLibraryIds(ids); uploadToken.current = crypto.randomUUID(); }} disabled={busy} />
      <Field label="Comparison goal" htmlFor="batch-goal"><textarea id="batch-goal" name="goal" value={goal} minLength={3} maxLength={2000} onChange={(e) => { setGoal(e.target.value); uploadToken.current = crypto.randomUUID(); }} required /></Field>
      <ActionButton type="submit" busy={busy} busyLabel="Saving comparison...">Upload and compare</ActionButton>
    </form></Surface>}
    {!comparisonId && !comparison && <EmptyState title="No comparison loaded" description="Upload two or more PDFs, or reopen saved work below." />}
    {!comparisonId && saved.length > 0 && <Surface><h2>Saved comparisons</h2>{saved.map((item) => <div className="paper-status-row" key={item.id}>
      <Link to={`/comparisons/${item.id}`}>{item.name}</Link><StatusBadge status={item.status} />
    </div>)}</Surface>}
    {comparison && <>
      <Surface><div className="batch-section-heading"><h2>{comparison.name}</h2><StatusBadge status={comparison.status} /></div>
        <p>Your comparison is saved. You can close this tab and return to this URL.</p>
        <Field label="Comparison name" htmlFor="saved-name"><input id="saved-name" value={name} maxLength={255} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Comparison goal" htmlFor="saved-goal"><textarea id="saved-goal" value={goal} maxLength={2000} onChange={(e) => setGoal(e.target.value)} /></Field>
        <div className="paper-row-actions">
          <ActionButton type="button" variant="secondary" disabled={!dirty || !name.trim() || goal.trim().length < 3} busy={busy} onClick={() => void action("save")}>Save details</ActionButton>
          <ActionButton type="button" disabled={dirty || activeStatuses.includes(comparison.status) || comparison.blocking_items.length > 0} busy={busy} onClick={() => void action("generate")}>Update comparison</ActionButton>
        </div>
        {dirty && <p role="status">Unsaved changes. Save details before generating a replacement.</p>}
        {comparison.outdated && <Alert tone="warning" title="Previous result"><p>This result uses an earlier goal or evidence generation. It remains available until you update the comparison.</p><p>Goal used: {comparison.result_goal ?? "Not recorded for this legacy result."}</p></Alert>}
        {comparison.error_message && <Alert tone="danger" title="Generation did not finish"><p>{comparison.error_message}</p></Alert>}
      </Surface>
      <Surface><h2>Comparison papers</h2>{comparison.papers.map((p) => <div className="paper-status-row" key={p.id}>
        <Link to={`/reader/${p.id}`}>{p.title}</Link><StatusBadge status={p.status} />
        {comparison.papers.length > 2 && <ActionButton type="button" variant="secondary" size="compact" disabled={busy} onClick={() => void action("remove", p.id)}>Remove from comparison</ActionButton>}
      </div>)}<LibraryPaperPicker key={comparison.id} selected={libraryIds} onChange={setLibraryIds} exclude={comparison.papers.map((p) => p.id)} maximum={10-comparison.papers.length} disabled={busy} />
      {libraryIds.length > 0 && <p>Use Save details above to add these papers. Updating the comparison is a separate action.</p>}</Surface>
      {comparison.blocking_items.map((blocker) => <Alert key={blocker.paper_id} tone="danger" title={blocker.title}><p>{blocker.error || "Paper analysis failed."}</p>
        {blocker.job_id && <ActionButton type="button" variant="secondary" busy={busy} onClick={() => void action("retry", blocker.paper_id)}>Retry paper analysis</ActionButton>}
      </Alert>)}
      <ExportPanel key={comparison.id} kind="comparison" id={comparison.id} revision={`${comparison.generation}:${comparison.updated_at}`} />
      {comparison.result_json && <ComparisonMatrix result={comparison.result_json} />}
    </>}
  </div>;
}

function ComparisonMatrix({ result }: { result: BatchSummaryResponse }) {
  return <Surface className="batch-comparison-panel">
    <div className="batch-section-heading"><h2>Comparison matrix</h2></div>
    <GenerationNotice mode={result.generation_mode} warnings={result.warnings} />
    <section className="batch-takeaway"><h3>Overall takeaway</h3><p>{result.overall_takeaway}</p></section>
    <p>Compare evaluation conditions alongside results. Scores from different tasks or datasets may not be directly comparable.</p>
    {result.papers.some((p) => !p.citations || Object.keys(p.citations).length === 0) && <Alert tone="warning" title="Source links unavailable in this saved result"><p>Older or limited results may not have cell citations. Update the comparison explicitly to generate an evidence-linked result.</p></Alert>}
    <div className="batch-matrix-scroll"><table className="batch-matrix" aria-label="Paper comparison matrix"><thead><tr><th scope="col">Dimension</th>{result.papers.map((p) => <th scope="col" key={p.paper_id}><Link to={`/reader/${p.paper_id}`}>{p.title}</Link></th>)}</tr></thead>
      <tbody>{dimensions.map((d) => <tr key={d.key}><th scope="row">{d.label}</th>{result.papers.map((p) => <td key={p.paper_id}><p>{p[d.key] ?? "Not recorded in saved result."}</p>
        {(p.citations?.[d.key] ?? []).map((citation,index) => <SourcePassage key={`${citation.chunk_id}-${index}`} citation={citation} />)}</td>)}</tr>)}</tbody>
    </table></div>
  </Surface>;
}

function message(error: unknown) { return error instanceof Error ? error.message : "Could not complete this action."; }
