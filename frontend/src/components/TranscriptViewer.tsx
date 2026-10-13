"use client";

import React, { useEffect, useRef } from "react";
import { TranscriptSegment } from "@/types/api";
import { getSpeakerBadgeColor } from "./SpeakerMapper";

interface TranscriptViewerProps {
  segments: TranscriptSegment[];
  highlightedSegmentId?: string | null;
  speakerMapping?: Record<string, string>;
  onSelectSegment?: (segmentId: string) => void;
}

function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
}

export default function TranscriptViewer({
  segments,
  highlightedSegmentId,
  speakerMapping = {},
  onSelectSegment,
}: TranscriptViewerProps) {
  const segmentRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    if (highlightedSegmentId && segmentRefs.current[highlightedSegmentId]) {
      segmentRefs.current[highlightedSegmentId]?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }
  }, [highlightedSegmentId]);

  if (!segments || segments.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-8 text-center text-slate-500">
        <p className="text-sm">No transcript segments available for this meeting.</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm flex flex-col h-[650px]">
      <div className="px-5 py-3.5 border-b border-slate-100 flex items-center justify-between bg-slate-50/50 rounded-t-xl">
        <h3 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
          <span>Transcript</span>
          <span className="text-xs font-normal text-slate-500">
            ({segments.length} segment{segments.length === 1 ? "" : "s"})
          </span>
        </h3>
        <span className="text-xs text-slate-400">Click any evidence link to jump to text</span>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3 divide-y divide-slate-100/60">
        {segments.map((seg) => {
          const isHighlighted = highlightedSegmentId === seg.segment_id;
          const speakerDisplay = seg.speaker_label
            ? speakerMapping[seg.speaker_label] || seg.speaker || seg.speaker_label
            : seg.speaker || "Unknown Speaker";
          const badgeColor = seg.speaker_label
            ? getSpeakerBadgeColor(seg.speaker_label)
            : "bg-slate-100 text-slate-600 border-slate-200";

          return (
            <div
              key={seg.segment_id}
              ref={(el) => {
                segmentRefs.current[seg.segment_id] = el;
              }}
              onClick={() => onSelectSegment?.(seg.segment_id)}
              className={`pt-3 first:pt-0 p-3 rounded-lg transition-all cursor-pointer ${
                isHighlighted
                  ? "bg-amber-50 ring-2 ring-amber-400 border-amber-200 shadow-sm"
                  : "hover:bg-slate-50/80 border border-transparent"
              }`}
            >
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                  <span
                    className={`inline-block px-2 py-0.5 rounded text-[11px] font-semibold border ${badgeColor}`}
                  >
                    {speakerDisplay}
                  </span>
                  <span className="text-[11px] font-mono text-slate-400">
                    {formatTime(seg.start_time)} – {formatTime(seg.end_time)}
                  </span>
                </div>
                <span className="text-[10px] font-mono text-slate-300">
                  #{seg.segment_id.slice(0, 8)}
                </span>
              </div>
              <p className="text-sm text-slate-700 leading-relaxed pl-1">
                {seg.text}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

