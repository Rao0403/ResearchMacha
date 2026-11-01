import type { ButtonHTMLAttributes, ReactNode } from "react";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "regular" | "compact";

interface ActionButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  busy?: boolean;
  busyLabel?: string;
  children: ReactNode;
}

export function ActionButton({
  variant = "primary",
  size = "regular",
  busy = false,
  busyLabel = "Working...",
  className,
  disabled,
  children,
  ...props
}: ActionButtonProps) {
  const classes = [
    "ui-button",
    `ui-button-${variant}`,
    size === "compact" ? "ui-button-compact" : null,
    className,
  ].filter(Boolean).join(" ");

  return (
    <button className={classes} disabled={disabled || busy} aria-busy={busy || undefined} {...props}>
      {busy ? busyLabel : children}
    </button>
  );
}
