"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Slider } from "@/components/ui";
import { cn } from "@/lib/utils";

/**
 * Paint over damage the automatic detector missed.
 *
 * The mask is kept on a canvas sized to the *source* image, not to the element on
 * screen, so what the worker receives matches the photograph pixel for pixel
 * regardless of how the browser laid it out or how the user zoomed.
 */
export function MaskCanvas({
  imageUrl,
  width,
  height,
  onChange,
  className,
}: {
  imageUrl: string;
  width: number;
  height: number;
  onChange: (blob: Blob | null) => void;
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const drawing = useRef(false);
  const lastPoint = useRef<{ x: number; y: number } | null>(null);
  const [brush, setBrush] = useState(28);
  const [erase, setErase] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.width = width;
    canvas.height = height;
    canvas.getContext("2d")?.clearRect(0, 0, width, height);
    setDirty(false);
    onChange(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imageUrl, width, height]);

  /** Map a pointer position to source-image coordinates. */
  const toCanvasPoint = useCallback((clientX: number, clientY: number) => {
    const wrap = wrapRef.current;
    if (!wrap) return null;
    const rect = wrap.getBoundingClientRect();
    return {
      x: ((clientX - rect.left) / rect.width) * width,
      y: ((clientY - rect.top) / rect.height) * height,
    };
  }, [width, height]);

  const strokeTo = useCallback(
    (x: number, y: number) => {
      const context = canvasRef.current?.getContext("2d");
      if (!context) return;

      // Scale the brush with the image so it feels the same on any size.
      const radius = (brush / 100) * Math.max(width, height) * 0.06;
      context.globalCompositeOperation = erase ? "destination-out" : "source-over";
      context.strokeStyle = "rgba(255,255,255,1)";
      context.fillStyle = "rgba(255,255,255,1)";
      context.lineWidth = radius * 2;
      context.lineCap = "round";
      context.lineJoin = "round";

      const previous = lastPoint.current;
      if (previous) {
        context.beginPath();
        context.moveTo(previous.x, previous.y);
        context.lineTo(x, y);
        context.stroke();
      } else {
        context.beginPath();
        context.arc(x, y, radius, 0, Math.PI * 2);
        context.fill();
      }
      lastPoint.current = { x, y };
      setDirty(true);
    },
    [brush, erase, width, height],
  );

  const publish = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    // Flatten to a hard black/white mask: the pipeline thresholds at 127, and an
    // anti-aliased brush edge would otherwise produce an ambiguous boundary.
    const flat = document.createElement("canvas");
    flat.width = canvas.width;
    flat.height = canvas.height;
    const context = flat.getContext("2d");
    if (!context) return;
    context.fillStyle = "#000";
    context.fillRect(0, 0, flat.width, flat.height);
    context.drawImage(canvas, 0, 0);

    const pixels = context.getImageData(0, 0, flat.width, flat.height);
    let painted = 0;
    for (let i = 0; i < pixels.data.length; i += 4) {
      const on = pixels.data[i + 3] > 8 && pixels.data[i] > 8;
      const value = on ? 255 : 0;
      if (on) painted += 1;
      pixels.data[i] = value;
      pixels.data[i + 1] = value;
      pixels.data[i + 2] = value;
      pixels.data[i + 3] = 255;
    }
    context.putImageData(pixels, 0, 0);

    if (painted === 0) {
      onChange(null);
      return;
    }
    flat.toBlob((blob) => onChange(blob), "image/png");
  }, [onChange]);

  function clear() {
    const canvas = canvasRef.current;
    canvas?.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
    setDirty(false);
    onChange(null);
  }

  return (
    <div className={cn("space-y-3", className)}>
      <div
        ref={wrapRef}
        className="relative overflow-hidden rounded-card border border-ink-line bg-ink"
        style={{ touchAction: "none" }}
        onPointerDown={(event) => {
          drawing.current = true;
          lastPoint.current = null;
          event.currentTarget.setPointerCapture(event.pointerId);
          const point = toCanvasPoint(event.clientX, event.clientY);
          if (point) strokeTo(point.x, point.y);
        }}
        onPointerMove={(event) => {
          if (!drawing.current) return;
          const point = toCanvasPoint(event.clientX, event.clientY);
          if (point) strokeTo(point.x, point.y);
        }}
        onPointerUp={(event) => {
          drawing.current = false;
          lastPoint.current = null;
          event.currentTarget.releasePointerCapture(event.pointerId);
          publish();
        }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={imageUrl} alt="Photograph to repair" className="block w-full" draggable={false} />
        <canvas
          ref={canvasRef}
          className="absolute inset-0 h-full w-full cursor-crosshair opacity-55 mix-blend-screen"
        />
      </div>

      <div className="grid grid-cols-[1fr_auto_auto] items-end gap-3">
        <Slider
          label={erase ? "Eraser size" : "Brush size"}
          value={brush}
          min={4}
          max={100}
          onChange={setBrush}
        />
        <button
          type="button"
          onClick={() => setErase((value) => !value)}
          aria-pressed={erase}
          className={cn("btn-ghost text-xs", erase && "border-turmeric/60 text-cotton")}
        >
          {erase ? "Erasing" : "Erase"}
        </button>
        <button type="button" onClick={clear} className="btn-ghost text-xs" disabled={!dirty}>
          Clear
        </button>
      </div>

      <p className="text-xs text-cotton-faint">
        Paint over tears, missing corners or stains. Anything you paint is repaired even if the
        detector did not flag it; everything you leave alone stays untouched.
      </p>
    </div>
  );
}
