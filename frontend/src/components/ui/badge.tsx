import * as React from "react";
import { cn } from "@/lib/utils";

export function Badge({
  className,
  variant = "default",
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { variant?: "default" | "secondary" }) {
  return (
    <span
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-full px-2.5 py-1 text-[12px] font-medium",
        variant === "default" && "bg-accent-soft text-accent-ink",
        variant === "secondary" && "bg-canvas text-ink-dim border border-line",
        className
      )}
      {...props}
    />
  );
}
