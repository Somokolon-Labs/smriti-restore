import type { Metadata } from "next";

import { ShowcaseGrid } from "@/components/showcase-grid";

export const metadata: Metadata = {
  title: "Showcase",
  description: "Before and after pairs, published with the consent of the people who uploaded them.",
};

export default function ShowcasePage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <header className="mb-8 max-w-2xl">
        <p className="label">Showcase</p>
        <h1 className="mt-2 font-display text-3xl text-cotton sm:text-4xl">Before and after</h1>
        <p className="mt-3 text-cotton-dim">
          Drag the handle to compare. Every pair here was published with the uploader&apos;s explicit
          consent and then featured by hand — there is no automatic feed of what people upload.
        </p>
      </header>

      <ShowcaseGrid />
    </div>
  );
}
