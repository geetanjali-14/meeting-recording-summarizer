"use client";

import React, { useState } from "react";

interface SpeakerMapperProps {
  detectedSpeakers: string[];
  speakerMapping: Record<string, string>;
  onMappingChange: (newMapping: Record<string, string>) => void;
}

const SPEAKER_COLORS = [
  "bg-blue-100 text-blue-800 border-blue-200",
  "bg-purple-100 text-purple-800 border-purple-200",
  "bg-emerald-100 text-emerald-800 border-emerald-200",
  "bg-amber-100 text-amber-800 border-amber-200",
  "bg-rose-100 text-rose-800 border-rose-200",
  "bg-indigo-100 text-indigo-800 border-indigo-200",
  "bg-teal-100 text-teal-800 border-teal-200",
];

export function getSpeakerBadgeColor(speakerLabel: string): string {
  let hash = 0;
  for (let i = 0; i < speakerLabel.length; i++) {
    hash = (hash << 5) - hash + speakerLabel.charCodeAt(i);
    hash |= 0;
  }
  const index = Math.abs(hash) % SPEAKER_COLORS.length;
  return SPEAKER_COLORS[index];
}

export default function SpeakerMapper({
  detectedSpeakers,
  speakerMapping,
  onMappingChange,
}: SpeakerMapperProps) {
  const [isOpen, setIsOpen] = useState(false);

  const handleNameChange = (speakerLabel: string, customName: string) => {
    const updated = { ...speakerMapping, [speakerLabel]: customName };
    onMappingChange(updated);
  };

  if (detectedSpeakers.length === 0) {
    return null;
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm mb-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
            <span>Detected Speakers ({detectedSpeakers.length})</span>
          </h3>
          <p className="text-xs text-slate-500 mt-0.5">
            Assign custom names to speaker labels. Names will immediately update across the transcript and evidence references.
          </p>
        </div>
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="text-xs font-medium text-indigo-600 hover:text-indigo-800 px-3 py-1.5 rounded-md border border-indigo-200 hover:bg-indigo-50 transition-colors"
        >
          {isOpen ? "Hide Speaker Editor" : "Edit Speaker Names"}
        </button>
      </div>

      {/* Pill summary when collapsed */}
      {!isOpen && (
        <div className="flex flex-wrap gap-2 mt-3 pt-3 border-t border-slate-100">
          {detectedSpeakers.map((label) => {
            const displayName = speakerMapping[label] || label;
            const badgeColor = getSpeakerBadgeColor(label);
            return (
              <span
                key={label}
                className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border ${badgeColor}`}
              >
                <span className="font-semibold mr-1">{displayName}</span>
                {speakerMapping[label] && (
                  <span className="opacity-60 text-[10px]">({label})</span>
                )}
              </span>
            );
          })}
        </div>
      )}

      {/* Editor list when expanded */}
      {isOpen && (
        <div className="mt-4 pt-4 border-t border-slate-100 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
          {detectedSpeakers.map((label) => {
            const badgeColor = getSpeakerBadgeColor(label);
            return (
              <div
                key={label}
                className="flex items-center gap-2 p-2 rounded-lg border border-slate-100 bg-slate-50/50"
              >
                <span
                  className={`px-2 py-1 rounded text-xs font-mono font-medium border flex-shrink-0 ${badgeColor}`}
                >
                  {label}
                </span>
                <input
                  type="text"
                  placeholder="Enter name..."
                  value={speakerMapping[label] || ""}
                  onChange={(e) => handleNameChange(label, e.target.value)}
                  className="flex-1 min-w-0 text-xs px-2.5 py-1.5 rounded border border-slate-300 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white"
                />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

