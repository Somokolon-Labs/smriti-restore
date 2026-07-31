import Link from "next/link";

import { Logo } from "@/components/logo";

export function SiteFooter() {
  return (
    <footer className="mt-24 border-t border-ink-line/80">
      <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
        <div className="flex flex-col gap-8 sm:flex-row sm:items-start sm:justify-between">
          <div className="max-w-sm">
            <div className="flex items-center gap-2 text-turmeric">
              <Logo className="h-6 w-6" />
              <span className="font-display text-base text-cotton">Smriti</span>
            </div>
            <p className="mt-3 text-sm leading-relaxed text-cotton-faint">
              Stable Diffusion 1.5 fine-tuned with LoRA on Bengali smriti kantha, jamdani and
              alpona motifs. Built by Somokolon Labs.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-8 text-sm sm:gap-14">
            <div>
              <p className="label mb-3">Product</p>
              <ul className="space-y-2 text-cotton-dim">
                <li>
                  <Link href="/restore" className="hover:text-cotton">
                    Studio
                  </Link>
                </li>
                <li>
                  <Link href="/showcase" className="hover:text-cotton">
                    Gallery
                  </Link>
                </li>
                <li>
                  <Link href="/model" className="hover:text-cotton">
                    Model card
                  </Link>
                </li>
              </ul>
            </div>
            <div>
              <p className="label mb-3">Engineering</p>
              <ul className="space-y-2 text-cotton-dim">
                <li>
                  <a
                    href="https://github.com/Somokolon-Labs/smriti-restore"
                    target="_blank"
                    rel="noreferrer noopener"
                    className="hover:text-cotton"
                  >
                    Source
                  </a>
                </li>
                <li>
                  <a
                    href={`${process.env.NEXT_PUBLIC_API_URL ?? ""}/docs`}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="hover:text-cotton"
                  >
                    API docs
                  </a>
                </li>
                <li>
                  <a
                    href={`${process.env.NEXT_PUBLIC_API_URL ?? ""}/metrics`}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="hover:text-cotton"
                  >
                    Metrics
                  </a>
                </li>
              </ul>
            </div>
          </div>
        </div>

        <div className="stitch-rule my-8" />

        <div className="flex flex-col gap-2 text-xs text-cotton-faint sm:flex-row sm:justify-between">
          <p>
            Adapter weights derive from Stable Diffusion v1.5 and inherit the CreativeML Open
            RAIL-M license.
          </p>
          <p>© {new Date().getFullYear()} Somokolon Labs</p>
        </div>
      </div>
    </footer>
  );
}
