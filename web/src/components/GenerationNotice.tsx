import type { GenerationMode, WarningMessage } from "../types";

interface GenerationNoticeProps {
  mode?: GenerationMode | null;
  warnings?: WarningMessage | WarningMessage[] | null;
  label?: string;
}

const modeCopy: Record<GenerationMode, { title: string; description: string }> = {
  ai: {
    title: "AI-generated result",
    description: "The model completed this result using the cited source evidence.",
  },
  extractive: {
    title: "Extractive fallback",
    description: "The AI provider could not complete this result, so it was assembled directly from source passages.",
  },
  mock: {
    title: "Mock result",
    description: "This output came from the configured mock provider and should not be treated as research evidence.",
  },
  unknown_legacy: {
    title: "Legacy result",
    description: "This output predates generation provenance tracking. Reanalyze it before relying on its generation mode.",
  },
};

export function GenerationNotice({ mode, warnings, label }: GenerationNoticeProps) {
  const messages = (Array.isArray(warnings) ? warnings : warnings ? [warnings] : []).filter(Boolean);
  if ((!mode || mode === "ai") && messages.length === 0) {
    return null;
  }

  const copy = mode ? modeCopy[mode] : modeCopy.ai;
  return (
    <aside className={`generation-notice generation-notice-${mode ?? "warning"}`} role="status">
      <strong>{label ?? copy.title}</strong>
      {mode && mode !== "ai" ? <p>{copy.description}</p> : null}
      {messages.map((warning, index) => <p key={`${warning}-${index}`}>{warning}</p>)}
    </aside>
  );
}
