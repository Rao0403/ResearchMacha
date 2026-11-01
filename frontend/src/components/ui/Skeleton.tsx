import type { CSSProperties } from "react";

interface SkeletonProps {
  width?: CSSProperties["width"];
  height?: CSSProperties["height"];
  label?: string;
}

export function Skeleton({ width = "100%", height = "1rem", label = "Loading" }: SkeletonProps) {
  return <span className="ui-skeleton" style={{ width, height }} role="status" aria-label={label} />;
}
