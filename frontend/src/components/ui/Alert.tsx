import type { HTMLAttributes, ReactNode } from "react";

export type AlertTone = "info" | "success" | "warning" | "danger";

interface AlertProps extends HTMLAttributes<HTMLElement> {
  tone?: AlertTone;
  title: string;
  children?: ReactNode;
}

export function Alert({ tone = "info", title, children, className, role = "status", ...props }: AlertProps) {
  return (
    <aside className={["ui-alert", `ui-alert-${tone}`, className].filter(Boolean).join(" ")} role={role} {...props}>
      <strong>{title}</strong>
      {children}
    </aside>
  );
}
