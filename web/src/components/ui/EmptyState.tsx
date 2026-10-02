import type { ReactNode } from "react";

interface EmptyStateProps {
  title: string;
  description: string;
  actions?: ReactNode;
}

export function EmptyState({ title, description, actions }: EmptyStateProps) {
  return (
    <section className="ui-empty-state">
      <h3>{title}</h3>
      <p>{description}</p>
      {actions ? <div className="ui-empty-state-actions">{actions}</div> : null}
    </section>
  );
}
