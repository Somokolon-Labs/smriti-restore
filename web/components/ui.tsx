"use client";

import { cn } from "@/lib/utils";

export function Slider({
  label,
  hint,
  value,
  min,
  max,
  step = 1,
  format,
  onChange,
  disabled,
}: {
  label: string;
  hint?: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  format?: (value: number) => string;
  onChange: (value: number) => void;
  disabled?: boolean;
}) {
  const id = `slider-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  return (
    <div className={cn(disabled && "opacity-50")}>
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="label">
          {label}
        </label>
        <span className="font-mono text-xs text-cotton">
          {format ? format(value) : value}
        </span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
        aria-describedby={hint ? `${id}-hint` : undefined}
      />
      {hint && (
        <p id={`${id}-hint`} className="mt-1.5 text-xs leading-snug text-cotton-faint">
          {hint}
        </p>
      )}
    </div>
  );
}

export function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: Array<{ value: T; label: string; hint?: string }>;
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div>
      <p className="label mb-2">{label}</p>
      <div
        role="radiogroup"
        aria-label={label}
        className="flex gap-1 rounded-lg border border-ink-line bg-ink/60 p-1"
      >
        {options.map((option) => {
          const active = option.value === value;
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={active}
              title={option.hint}
              onClick={() => onChange(option.value)}
              className={cn(
                "flex-1 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors",
                active
                  ? "bg-turmeric text-ink"
                  : "text-cotton-dim hover:bg-ink-raised hover:text-cotton",
              )}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function Callout({
  tone = "info",
  title,
  children,
}: {
  tone?: "info" | "warn" | "error";
  title?: string;
  children: React.ReactNode;
}) {
  const tones = {
    info: "border-indigo-light/40 bg-indigo/20 text-cotton-dim",
    warn: "border-turmeric/40 bg-turmeric/10 text-cotton-dim",
    error: "border-madder/50 bg-madder/15 text-cotton",
  } as const;

  return (
    <div className={cn("rounded-lg border px-3.5 py-3 text-sm leading-relaxed", tones[tone])}>
      {title && <p className="mb-1 font-medium text-cotton">{title}</p>}
      {children}
    </div>
  );
}

export function Stat({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: boolean;
}) {
  return (
    <div className="surface p-4">
      <p className="label">{label}</p>
      <p
        className={cn(
          "mt-2 font-display text-2xl leading-none",
          accent ? "text-turmeric" : "text-cotton",
        )}
      >
        {value}
      </p>
      {sub && <p className="mt-1.5 text-xs text-cotton-faint">{sub}</p>}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={cn("h-4 w-4 animate-stitch-spin", className)}
      aria-hidden
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeDasharray="14 44"
        strokeLinecap="round"
      />
    </svg>
  );
}
