"use client";

import { X, type LucideIcon } from "lucide-react";
import { useEffect, useRef, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/skive";

type Variant = "default" | "primary" | "ghost" | "danger";
const variants: Record<Variant, string> = {
  default: "border border-line bg-surface hover:bg-hover",
  primary: "bg-accent text-accent-text hover:opacity-90",
  ghost: "hover:bg-hover",
  danger: "border border-line text-danger hover:bg-danger-soft",
};

export function Button({ variant = "default", size = "md", className, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" | "icon" }) {
  return (
    <button
      type="button"
      {...props}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-md font-medium whitespace-nowrap transition-colors disabled:opacity-50",
        size === "sm" ? "h-7 px-2 text-xs" : size === "icon" ? "h-8 w-8" : "h-8 px-3 text-[13px]",
        variants[variant],
        className,
      )}
    />
  );
}

const field = "w-full rounded-md border border-line bg-surface px-2.5 text-[13px] text-ink outline-none placeholder:text-muted focus:border-accent";

export const Input = ({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) => <input {...props} className={cn(field, "h-8", className)} />;
export const Textarea = ({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...props} className={cn(field, "min-h-20 py-2", className)} />;
export const Select = ({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) => <select {...props} className={cn(field, "h-8 pr-1", className)} />;

export function Field({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <label className={cn("block text-xs font-medium text-muted", className)}>
      <span className="mb-1 block">{label}</span>
      {children}
    </label>
  );
}

export function Badge({ tone = "neutral", children, className }: { tone?: "neutral" | "accent" | "warn" | "danger"; children: ReactNode; className?: string }) {
  const tones = { neutral: "bg-hover text-muted", accent: "bg-accent-soft text-accent", warn: "bg-warn-soft text-warn", danger: "bg-danger-soft text-danger" };
  return <span className={cn("inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap", tones[tone], className)}>{children}</span>;
}

export const Card = ({ className, children }: { className?: string; children: ReactNode }) => <div className={cn("rounded-lg border border-line bg-surface p-4", className)}>{children}</div>;

export const Skeleton = ({ className }: { className?: string }) => <div className={cn("animate-pulse rounded bg-hover", className)} />;

export function RowsSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-2 py-2">
      {Array.from({ length: rows }, (_, index) => <Skeleton key={index} className="h-9 w-full" />)}
    </div>
  );
}

export function EmptyState({ icon: Icon, title, hint, children }: { icon: LucideIcon; title: string; hint?: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-line px-6 py-14 text-center">
      <Icon className="h-7 w-7 text-muted" strokeWidth={1.5} />
      <p className="font-medium">{title}</p>
      {hint && <p className="max-w-md text-[13px] text-muted">{hint}</p>}
      {children && <div className="mt-2 flex flex-wrap justify-center gap-2">{children}</div>}
    </div>
  );
}

export function PageHeader({ title, hint, children }: { title: string; hint?: string; children?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold">{title}</h1>
        {hint && <p className="mt-0.5 text-[13px] text-muted">{hint}</p>}
      </div>
      {children && <div className="flex flex-wrap gap-2">{children}</div>}
    </div>
  );
}

export function Dialog({ open, onClose, title, children, size = "md", footer }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; size?: "sm" | "md" | "lg" | "xl"; footer?: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  const widths = { sm: "max-w-sm", md: "max-w-lg", lg: "max-w-3xl", xl: "max-w-5xl" };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div role="dialog" aria-modal="true" className={cn("flex max-h-[90vh] w-full flex-col rounded-xl border border-line bg-surface shadow-xl", widths[size])}>
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          <h2 className="min-w-0 truncate font-semibold">{title}</h2>
          <Button variant="ghost" size="icon" aria-label="닫기" onClick={onClose}><X className="h-4 w-4" /></Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-4 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function Menu({ trigger, children }: { trigger: (toggle: () => void) => ReactNode; children: (close: () => void) => ReactNode }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => { if (!box.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);
  return (
    <div className="relative" ref={box}>
      {trigger(() => setOpen((value) => !value))}
      {open && <div role="menu" className="absolute right-0 z-40 mt-1 min-w-44 rounded-lg border border-line bg-surface p-1 shadow-lg">{children(() => setOpen(false))}</div>}
    </div>
  );
}

export function MenuItem({ icon: Icon, danger, onClick, children }: { icon?: LucideIcon; danger?: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" role="menuitem" onClick={onClick} className={cn("flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[13px] hover:bg-hover", danger && "text-danger")}>
      {Icon && <Icon className="h-3.5 w-3.5" />}
      {children}
    </button>
  );
}

export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (value: T) => void; items: [T, string][] }) {
  return (
    <div className="flex gap-1 border-b border-line">
      {items.map(([key, label]) => (
        <button key={key} type="button" onClick={() => onChange(key)} className={cn("-mb-px border-b-2 px-3 py-1.5 text-[13px]", value === key ? "border-accent font-medium" : "border-transparent text-muted hover:text-ink")}>
          {label}
        </button>
      ))}
    </div>
  );
}
