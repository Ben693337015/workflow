import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-semibold transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-strong focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-accent-strong text-white shadow-sm hover:bg-accent-deep hover:shadow-md active:translate-y-px",
        outline: "border border-line-strong bg-surface text-ink hover:bg-canvas",
        ghost: "text-ink-dim hover:bg-canvas hover:text-ink",
        destructive: "text-danger hover:bg-danger-soft",
      },
      size: {
        default: "h-10 px-5",
        sm: "h-8 px-3 text-[13px]",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export function Button({ className, variant, size, ...props }: ButtonProps) {
  return <button className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}
