import type { HTMLAttributes } from "react";

type SurfaceTone = "default" | "subtle" | "inset";

interface SurfaceProps extends HTMLAttributes<HTMLElement> {
  as?: "section" | "article" | "div";
  tone?: SurfaceTone;
}

export function Surface({ as: Component = "section", tone = "default", className, ...props }: SurfaceProps) {
  return <Component className={["ui-surface", `ui-surface-${tone}`, className].filter(Boolean).join(" ")} {...props} />;
}
