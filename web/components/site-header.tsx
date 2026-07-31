"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { Logo } from "@/components/logo";
import { WorkerStatusPill } from "@/components/worker-status";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/restore", label: "Restore" },
  { href: "/showcase", label: "Showcase" },
  { href: "/model", label: "Model card" },
];

const REPO_URL = "https://github.com/Somokolon-Labs/smriti-restore";

export function SiteHeader() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-40 border-b border-ink-line/80 bg-ink/85 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-4 px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2.5 text-turmeric">
          <Logo />
          <span className="font-display text-lg tracking-tight text-cotton">Smriti</span>
        </Link>

        <nav className="ml-4 hidden items-center gap-1 md:flex" aria-label="Main">
          {NAV.map((item) => {
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-sm transition-colors",
                  active
                    ? "bg-ink-raised text-cotton"
                    : "text-cotton-dim hover:bg-ink-raised/60 hover:text-cotton",
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <WorkerStatusPill className="hidden sm:inline-flex" />
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer noopener"
            className="hidden text-sm text-cotton-dim transition-colors hover:text-cotton sm:block"
          >
            GitHub
          </a>
          <Link href="/restore" className="btn-primary hidden text-sm md:inline-flex">
            Restore
          </Link>
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            className="btn-ghost px-2 py-1.5 md:hidden"
            aria-expanded={open}
            aria-label="Toggle navigation"
          >
            <span className="block h-px w-5 bg-current" />
            <span className="sr-only">Menu</span>
          </button>
        </div>
      </div>

      {open && (
        <nav className="border-t border-ink-line px-4 pb-4 md:hidden" aria-label="Mobile">
          <div className="flex flex-col gap-1 pt-2">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setOpen(false)}
                className="rounded-lg px-3 py-2 text-sm text-cotton-dim hover:bg-ink-raised hover:text-cotton"
              >
                {item.label}
              </Link>
            ))}
            <WorkerStatusPill className="mt-2 self-start" />
          </div>
        </nav>
      )}
    </header>
  );
}
