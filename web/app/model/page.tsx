import type { Metadata } from "next";

import { EvalReport } from "@/components/model/eval-report";

export const metadata: Metadata = {
  title: "Model card",
  description:
    "How Smriti restores photographs, what it measurably recovers, and where it fails.",
};

export default function ModelPage() {
  return (
    <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <header className="mb-10 max-w-2xl">
        <p className="label">Model card</p>
        <h1 className="mt-2 font-display text-3xl text-cotton sm:text-4xl">
          What it recovers, and what it invents
        </h1>
        <p className="mt-3 text-cotton-dim">
          Restoration has ground truth available: degrade a clean photograph in a known way, restore
          it, and compare against the original. Everything below is read from the evaluation harness
          at runtime.
        </p>
      </header>

      <EvalReport />

      <section className="mt-14 space-y-6">
        <div>
          <h2 className="label mb-3">The pipeline</h2>
          <ol className="max-w-2xl space-y-3 text-sm leading-relaxed text-cotton-dim">
            <li>
              <span className="text-cotton">Damage repair.</span> Top-hat and black-hat morphology
              isolate defects; components are kept or rejected by fill ratio, which is
              orientation-independent, so a diagonal scratch is detected as readily as a vertical
              one. Stable Diffusion inpainting then repairs each region, composited back through a
              feathered mask so untouched pixels are preserved.
            </li>
            <li>
              <span className="text-cotton">Denoise.</span> Non-local means, blended back against the
              original so real film grain survives. Fidelity controls how much.
            </li>
            <li>
              <span className="text-cotton">Colourisation.</span> Colour is inferred by img2img on a
              reduced copy, then only the LAB chroma channels are transferred onto the original
              luminance. Measured luminance drift is under 1 part in 255, so no detail is lost — but
              the colours themselves are invented.
            </li>
            <li>
              <span className="text-cotton">Super-resolution.</span> The x4 diffusion upscaler over
              overlapping tiles, feathered at the seams, with a per-tile fallback to resampling if a
              tile exhausts VRAM. One bad tile degrades, it does not fail the job.
            </li>
            <li>
              <span className="text-cotton">Face restoration.</span> Faces are located with three
              OpenCV cascades (frontal, alt2 and mirrored profile) and refined by a low-strength
              img2img pass, capped so identity cannot drift far.
            </li>
          </ol>
        </div>

        <div>
          <h2 className="label mb-3">Limitations</h2>
          <ul className="max-w-2xl list-disc space-y-2 pl-5 text-sm leading-relaxed text-cotton-dim">
            <li>
              <span className="text-cotton">Face detection misses non-frontal poses.</span> On a
              sample of real portraits, the cascades found faces in four of six images. A missed face
              is left untouched rather than damaged, which is the safe failure, but this is
              face-aware refinement and not a dedicated face-restoration network.
            </li>
            <li>
              <span className="text-cotton">Colour is fabricated.</span> Colourisation produces a
              plausible interpretation, never a recovery. Clothing colours, in particular, are
              guesses and should not be treated as historical evidence.
            </li>
            <li>
              <span className="text-cotton">Detail at high upscale factors is synthesised.</span> 4x
              super-resolution invents texture that was never in the negative. It looks right; it is
              not evidence.
            </li>
            <li>
              <span className="text-cotton">Very heavy damage exceeds the detector.</span> Above
              roughly a third of the frame the automatic detector refuses to act, on the grounds that
              it has probably latched onto texture. Use the manual brush for large tears.
            </li>
            <li>
              <span className="text-cotton">Text, small print and fine patterns</span> are unreliable
              through inpainting and upscaling, as in the underlying SD 1.5 base model.
            </li>
          </ul>
        </div>

        <div>
          <h2 className="label mb-3">Do not use this for</h2>
          <p className="max-w-2xl text-sm leading-relaxed text-cotton-dim">
            Forensic, legal, medical or journalistic purposes. Every generative stage adds detail
            that was not in the original, and a restored photograph is an interpretation. It is
            excellent for a family album and inadmissible as evidence.
          </p>
        </div>
      </section>
    </div>
  );
}
