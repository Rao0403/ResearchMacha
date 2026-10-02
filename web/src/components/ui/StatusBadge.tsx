import type { ReactNode } from "react";

type StatusTone = "neutral" | "info" | "success" | "warning" | "danger";

const statusTones: Record<string, StatusTone> = {
  ready: "success",
  completed: "success",
  done: "success",
  queued: "warning",
  pending: "warning",
  processing: "warning",
  importing: "warning",
  analyzing: "warning",
  synthesis_queued: "warning",
  synthesizing: "warning",
  degraded: "warning",
  completed_with_warnings: "warning",
  failed: "danger",
  blocked: "danger",
};

interface StatusBadgeProps {
  status: string;
  label?: string;
  icon?: ReactNode;
  tone?: StatusTone;
}

export function StatusBadge({ status, label, icon, tone = statusTones[status] ?? "neutral" }: StatusBadgeProps) {
  return (
    <span className={`ui-status-badge ui-status-badge-${tone}`} data-status={status}>
      {icon}
      {label ?? status.replaceAll("_", " ")}
    </span>
  );
}
