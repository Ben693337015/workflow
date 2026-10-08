"use client";

import * as React from "react";
import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import { cn } from "@/lib/utils";

export const DropdownMenu = DropdownMenuPrimitive.Root;
export const DropdownMenuTrigger = DropdownMenuPrimitive.Trigger;

export function DropdownMenuContent({
  className,
  sideOffset = 8,
  align = "end",
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Content>) {
  return (
    <DropdownMenuPrimitive.Portal>
      <DropdownMenuPrimitive.Content
        sideOffset={sideOffset}
        align={align}
        className={cn(
          "z-50 min-w-[15rem] overflow-hidden rounded-xl border border-line bg-surface p-1.5 shadow-[0_8px_30px_-6px_rgba(18,21,28,0.18)]",
          "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95",
          className
        )}
        {...props}
      />
    </DropdownMenuPrimitive.Portal>
  );
}

export function DropdownMenuItem({
  className,
  destructive,
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Item> & { destructive?: boolean }) {
  return (
    <DropdownMenuPrimitive.Item
      className={cn(
        // grille fixe icone/texte : garantit que chaque libelle (y compris
        // "Deconnexion") s'aligne sur la meme colonne, quelle que soit la
        // largeur de son icone.
        "grid grid-cols-[18px_1fr] items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13.5px] leading-none outline-none",
        "text-ink-dim hover:bg-canvas hover:text-ink focus:bg-canvas focus:text-ink cursor-pointer transition-colors",
        destructive && "text-danger hover:bg-danger-soft hover:text-danger focus:bg-danger-soft focus:text-danger",
        className
      )}
      {...props}
    />
  );
}

export function DropdownMenuLabel({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("px-2.5 py-2", className)} {...props} />;
}

export function DropdownMenuSeparator({
  className,
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Separator>) {
  return (
    <DropdownMenuPrimitive.Separator className={cn("my-1 h-px bg-line", className)} {...props} />
  );
}
