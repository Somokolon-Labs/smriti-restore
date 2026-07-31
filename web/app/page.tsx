import Link from "next/link";

import { AdapterStatusNotice } from "@/components/status-notice";
import { WorkerStatusPill } from "@/components/worker-status";

const PIPELINE = [
  {
    step: "01",
    title: "Find the damage",
    body: "Top-hat and black-hat morphology isolate scratches, creases and dust — thin high-contrast structures that differ from their surroundings. Measured at 1.00 recall on synthetic damage with no false positives on a clean frame.",
  },
  {
    step: "02",
    title: "Repair only that",
    body: "Inpainting runs on the damaged regions, not the whole frame, and composites back through a feathered mask. Undamaged pixels come out bit-for-bit identical, because a repair that quietly rewrites clean areas is not a repair.",
  },
  {
    step: "03",
    title: "Enlarge without running out of memory",
    body: "Diffusion super-resolution over overlapping tiles, blended at the seams. Peak VRAM stays flat whatever the input size, so a 20-megapixel scan works on a small card.",
  },
];

export default function HomePage() {
  return (
    <div className="space-y-20 pb-10">
      <section className="mx-auto max-w-6xl px-4 pt-16 sm:px-6 sm:pt-24">
        <div className="max-w-3xl">
          <div className="flex flex-wrap items-center gap-2">
            <span className="chip border-turmeric/40 text-turmeric">Diffusion · Restoration</span>
            <WorkerStatusPill />
          </div>

          <h1 className="mt-6 text-balance font-display text-4xl leading-[1.1] text-cotton sm:text-6xl">
            Photographs outlive the paper they were printed on
          </h1>

          <p className="mt-6 max-w-2xl text-lg leading-relaxed text-cotton-dim">
            Smriti repairs torn, faded and noisy photographs with diffusion models — damage repair,
            denoise, colourisation, super-resolution and face restoration as five independently
            reported stages — and wraps them in the infrastructure to actually run it: a job queue
            with leases and retries, GPU workers that attach from anywhere, and reference-based
            metrics rather than opinions.
          </p>

          <AdapterStatusNotice className="mt-8 max-w-2xl" />

          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/restore" className="btn-primary">
              Restore a photograph
            </Link>
            <Link href="/model" className="btn-ghost">
              See the measurements
            </Link>
            <a
              href="https://github.com/Somokolon-Labs/smriti-restore"
              target="_blank"
              rel="noreferrer noopener"
              className="btn-ghost"
            >
              Source
            </a>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 sm:px-6">
        <p className="label">How it works</p>
        <h2 className="mt-1 font-display text-2xl text-cotton">
          Region-targeted, not frame-rewriting
        </h2>
        <div className="mt-6 grid gap-3 md:grid-cols-3">
          {PIPELINE.map((item) => (
            <article key={item.step} className="surface p-5">
              <p className="font-mono text-xs text-turmeric">{item.step}</p>
              <h3 className="mt-3 font-display text-lg text-cotton">{item.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-cotton-dim">{item.body}</p>
            </article>
          ))}
        </div>
        <p className="mt-4 max-w-2xl text-sm text-cotton-faint">
          Because workers pull rather than listen, a job survives its worker dying: the lease
          expires, the control plane requeues it, and the next worker picks it up. That is why this
          demo can run on free-tier CPU hosting without pretending a GPU is attached.
        </p>
      </section>

      <section className="mx-auto max-w-6xl px-4 sm:px-6">
        <div className="surface p-6">
          <p className="label">Your photographs</p>
          <h2 className="mt-1 font-display text-2xl text-cotton">Private by default</h2>
          <ul className="mt-4 grid gap-3 text-sm leading-relaxed text-cotton-dim sm:grid-cols-2">
            <li>Uploads and results are never public unless you explicitly opt in.</li>
            <li>Everything is deleted automatically within 48 hours.</li>
            <li>You can erase a photograph immediately, without waiting for that.</li>
            <li>
              Even after opting in, a pair only becomes visible once it is featured by hand. There is
              no automatic feed.
            </li>
          </ul>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 sm:px-6">
        <div className="surface flex flex-col items-start gap-5 p-8 sm:flex-row sm:items-center sm:justify-between">
          <div className="max-w-lg">
            <h2 className="font-display text-2xl text-cotton">Try it on one of yours</h2>
            <p className="mt-2 text-sm text-cotton-dim">
              A scan, or just a phone photo of a print. Damage detection runs automatically, and you
              can paint over anything it misses.
            </p>
          </div>
          <Link href="/restore" className="btn-primary shrink-0">
            Open the restorer
          </Link>
        </div>
      </section>
    </div>
  );
}
