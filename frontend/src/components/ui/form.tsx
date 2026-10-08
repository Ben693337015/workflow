import * as React from "react";
import { cn } from "@/lib/utils";

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-11 rounded-xl border border-line-strong bg-surface px-3.5 text-[14px] text-ink shadow-sm outline-none transition",
        "placeholder:text-ink-faint hover:border-ink-faint focus:border-accent focus:ring-4 focus:ring-accent/15",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    />
  );
}

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label className={cn("text-[12.5px] font-semibold tracking-wide text-ink-dim", className)} {...props} />
  );
}

export function Select({
  className,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "h-11 rounded-xl border border-line-strong bg-surface px-3.5 text-[14px] text-ink shadow-sm outline-none transition",
        "hover:border-ink-faint focus:border-accent focus:ring-4 focus:ring-accent/15",
        className
      )}
      {...props}
    />
  );
}

export function Textarea({
  className,
  ...props
}: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        "min-h-[104px] resize-y rounded-xl border border-line-strong bg-surface px-3.5 py-3 text-[14px] text-ink shadow-sm outline-none transition",
        "placeholder:text-ink-faint hover:border-ink-faint focus:border-accent focus:ring-4 focus:ring-accent/15",
        className
      )}
      {...props}
    />
  );
}

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("carte-formulaire overflow-hidden rounded-2xl border border-line bg-surface", className)}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-6 py-6 sm:px-8", className)} {...props} />;
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h2 className={cn("text-[18px] font-semibold tracking-tight text-ink", className)} {...props} />;
}

export function CardDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("mt-0.5 text-[12.5px] text-ink-dim", className)} {...props} />;
}

export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("border-t border-line px-6 py-7 sm:px-8", className)} {...props} />;
}

export function Alert({
  className,
  variant = "destructive",
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { variant?: "destructive" | "success" }) {
  return (
    <div
      role="alert"
      className={cn(
        "rounded-lg px-3.5 py-2.5 text-[13px]",
        variant === "destructive" && "bg-danger-soft text-danger",
        variant === "success" && "bg-accent-soft text-accent-ink",
        className
      )}
      {...props}
    />
  );
}
