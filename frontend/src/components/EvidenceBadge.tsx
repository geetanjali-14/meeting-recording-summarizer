"use client";

import React from "react";

interface EvidenceBadgeProps {
  segmentIds: string[];
  onSelectSegment?: (segmentId: string) => void;
  activeSegmentId?: string | null;
}

export default function EvidenceBadge({
  segmentIds,
  onSelectSegment,
  activeSegmentId,
}: EvidenceBadgeProps) {
  if (!segmentIds || segmentIds.length === 0) {
    return (
      <span className="text-[11px] text-slate-400 italic">
        No direct citation
      </span>
    );
  }

  return (
    <div className="inline-flex flex-wrap items-center gap-1.5 mt-1.5">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
        Evidence:
      </span>
      {segmentIds.map((id) => {
        const isActive = activeSegmentId === id;
        const shortId = id.slice(0, 8);
        return (
          <button
            key={id}
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onSelectSegment?.(id);
            }}
            className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-mono font-medium transition-colors border ${
              isActive
                ? "bg-amber-100 text-amber-900 border-amber-300 ring-2 ring-amber-400/50"
                : "bg-slate-100 text-slate-700 border-slate-200 hover:bg-indigo-50 hover:text-indigo-700 hover:border-indigo-200"
            }`}
            title={`Jump to segment ${id}`}
          >
            <span className="mr-0.5">#</span>
            {shortId}
          </button>
        );
      })}
    </div>
  );
}

