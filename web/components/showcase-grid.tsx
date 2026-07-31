"use client";

import { useCallback, useEffect, useState } from "react";

import { CompareSlider } from "@/components/compare-slider";
import { Callout, Spinner } from "@/components/ui";
import { absoluteUrl, api } from "@/lib/api";
import type { ShowcaseItem } from "@/lib/types";
import { formatDuration, relativeTime } from "@/lib/utils";

export function ShowcaseGrid() {
  const [items, setItems] = useState<ShowcaseItem[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (reset: boolean) => {
      setLoading(true);
      setError(null);
      try {
        const page = await api.getShowcase({
          limit: 8,
          cursor: reset ? undefined : (cursor ?? undefined),
        });
        setItems((prev) => (reset || prev === null ? page.items : [...prev, ...page.items]));
        setCursor(page.next_cursor);
      } catch {
        setError("Could not load the showcase.");
        setItems((prev) => prev ?? []);
      } finally {
        setLoading(false);
      }
    },
    [cursor],
  );

  useEffect(() => {
    void load(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (error) return <Callout tone="error">{error}</Callout>;

  if (items === null) {
    return (
      <p className="flex items-center gap-2 text-sm text-cotton-faint">
        <Spinner /> loading
      </p>
    );
  }

  if (items.length === 0) {
    return (
      <div className="surface p-10 text-center">
        <p className="font-display text-lg text-cotton">Nothing published yet</p>
        <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-cotton-faint">
          Restorations only appear here when the person who uploaded the photograph opted in and the
          pair was then featured by hand. Two gates, both deliberate — these are family photographs,
          not stock images.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="grid gap-6 md:grid-cols-2">
        {items.map((item) => (
          <figure key={item.job_id} className="surface overflow-hidden">
            <CompareSlider
              beforeUrl={absoluteUrl(item.before_url)}
              afterUrl={absoluteUrl(item.after_url)}
              beforeLabel="Before"
              afterLabel="After"
            />
            <figcaption className="space-y-2 p-4">
              <div className="flex flex-wrap gap-1.5">
                <span className="chip">{item.profile.replace(/_/g, " ")}</span>
                <span className="chip">
                  {item.source_width}×{item.source_height} → {item.result_width}×
                  {item.result_height}
                </span>
                <span className="chip">{(item.damage_ratio * 100).toFixed(2)}% repaired</span>
                {item.faces_found > 0 && <span className="chip">{item.faces_found} faces</span>}
                <span className="chip">{formatDuration(item.duration_ms)}</span>
              </div>
              {item.notes && (
                <p className="text-xs leading-relaxed text-cotton-faint">{item.notes}</p>
              )}
              <p className="font-mono text-[10px] text-cotton-faint">
                {item.stages.join(" → ").replace(/_/g, " ")} · {relativeTime(item.created_at)}
              </p>
            </figcaption>
          </figure>
        ))}
      </div>

      {cursor && (
        <div className="text-center">
          <button
            type="button"
            className="btn-ghost text-sm"
            disabled={loading}
            onClick={() => void load(false)}
          >
            {loading ? "loading…" : "Load more"}
          </button>
        </div>
      )}
    </div>
  );
}
