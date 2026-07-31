"use client";

import { useCallback, useRef, useState } from "react";

/**
 * Before/after wipe for img2img, inpaint and upscale results.
 * Pointer, keyboard and touch all drive the same handle.
 */
export function CompareSlider({
  beforeUrl,
  afterUrl,
  beforeLabel = "Input",
  afterLabel = "Result",
  className = "",
}: {
  beforeUrl: string;
  afterUrl: string;
  beforeLabel?: string;
  afterLabel?: string;
  className?: string;
}) {
  const [position, setPosition] = useState(50);
  const frameRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const setFromClientX = useCallback((clientX: number) => {
    const frame = frameRef.current;
    if (!frame) return;
    const rect = frame.getBoundingClientRect();
    const ratio = ((clientX - rect.left) / rect.width) * 100;
    setPosition(Math.min(100, Math.max(0, ratio)));
  }, []);

  return (
    <div
      ref={frameRef}
      className={`relative select-none overflow-hidden rounded-card border border-ink-line bg-ink ${className}`}
      onPointerDown={(event) => {
        dragging.current = true;
        event.currentTarget.setPointerCapture(event.pointerId);
        setFromClientX(event.clientX);
      }}
      onPointerMove={(event) => {
        if (dragging.current) setFromClientX(event.clientX);
      }}
      onPointerUp={(event) => {
        dragging.current = false;
        event.currentTarget.releasePointerCapture(event.pointerId);
      }}
    >
      {/* The result sets the frame size; the input is clipped on top of it. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={afterUrl} alt={afterLabel} className="block w-full" draggable={false} />

      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={beforeUrl}
        alt={beforeLabel}
        draggable={false}
        className="absolute inset-0 h-full w-full object-cover"
        style={{ clipPath: `inset(0 ${100 - position}% 0 0)` }}
      />

      <div
        className="absolute inset-y-0 w-px bg-turmeric"
        style={{ left: `${position}%` }}
        aria-hidden
      />

      <input
        type="range"
        min={0}
        max={100}
        step={0.5}
        value={position}
        onChange={(event) => setPosition(Number(event.target.value))}
        aria-label="Compare before and after"
        className="absolute inset-x-0 bottom-3 mx-auto !w-[85%] cursor-ew-resize opacity-70 hover:opacity-100"
      />

      <span className="chip pointer-events-none absolute left-3 top-3 bg-ink/80">{beforeLabel}</span>
      <span className="chip pointer-events-none absolute right-3 top-3 bg-ink/80">{afterLabel}</span>
    </div>
  );
}
