import type { Metadata } from "next";

import { RestoreStudio } from "@/components/restore/restore-studio";
import { AdapterStatusNotice } from "@/components/status-notice";

export const metadata: Metadata = {
  title: "Restore",
  description:
    "Repair damage, reduce noise, colourise, upscale and restore faces in old photographs.",
};

export default function RestorePage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <header className="mb-6 max-w-2xl">
        <p className="label">Restore</p>
        <h1 className="mt-2 font-display text-3xl text-cotton sm:text-4xl">
          Bring a photograph back
        </h1>
        <p className="mt-3 text-balance text-cotton-dim">
          Upload a scan or a phone photo of a print. Damage is found automatically, repaired region
          by region, and everything undamaged is left exactly as it was.
        </p>
      </header>

      <AdapterStatusNotice className="mb-8 max-w-3xl" />

      <RestoreStudio />

      <p className="mt-8 max-w-3xl text-xs leading-relaxed text-cotton-faint">
        Your photograph is private. It is not shown to anyone, is deleted automatically within 48
        hours, and you can erase it immediately with the delete button once a restoration finishes.
        Nothing reaches the public showcase unless you opt in and it is then featured by hand.
      </p>
    </div>
  );
}
