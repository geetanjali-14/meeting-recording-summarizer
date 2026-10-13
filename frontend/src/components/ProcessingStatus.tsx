"use client";

import React, { useEffect, useState, useRef, useCallback } from "react";
import { api } from "@/lib/api";
import { JobStatusResponse, JobStage } from "@/types/api";

interface ProcessingStatusProps {
  meetingId: string;
  onCompleted?: () => void;
  onFailed?: (error: string) => void;
}

const STAGES: { stage: JobStage; label: string; desc: string; percent: number }[] = [
  { stage: "VALIDATING", label: "Validating", desc: "Checking file headers and integrity", percent: 15 },
  { stage: "EXTRACTING_AUDIO", label: "Extracting Audio", desc: "Demuxing and resampling audio stream", percent: 30 },
  { stage: "TRANSCRIBING", label: "Transcribing", desc: "Speech-to-text with Groq Whisper", percent: 50 },
  { stage: "DIARIZING", label: "Diarizing", desc: "Speaker separation with Pyannote", percent: 70 },
  { stage: "ANALYZING", label: "Analyzing", desc: "Extracting summary, decisions, action items", percent: 85 },
  { stage: "VERIFYING", label: "Verifying", desc: "Validating citations and hallucination guardrails", percent: 92 },
  { stage: "SAVING", label: "Finalizing", desc: "Persisting intelligence and transcripts", percent: 98 },
];

export default function ProcessingStatus({
  meetingId,
  onCompleted,
  onFailed,
}: ProcessingStatusProps) {
  const [jobStatus, setJobStatus] = useState<JobStatusResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const isMountedRef = useRef<boolean>(true);
  const pollCountRef = useRef<number>(0);
  const maxPolls = 150; // max ~5-6 minutes

  const fetchStatus = useCallback(async () => {
    try {
      const res = await api.getStatus(meetingId);
      if (!isMountedRef.current) return;
      setJobStatus(res.data);
      setError(null);
      setIsLoading(false);

      if (res.data.status === "COMPLETED") {
        if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
        onCompleted?.();
      } else if (res.data.status === "FAILED") {
        if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
        onFailed?.(res.data.error_message || "Processing failed");
      }
    } catch (err: unknown) {
      if (!isMountedRef.current) return;
      const msg = err instanceof Error ? err.message : "Failed to fetch status";
      setError(msg);
      setIsLoading(false);
    }
  }, [meetingId, onCompleted, onFailed]);

  useEffect(() => {
    isMountedRef.current = true;
    pollCountRef.current = 0;
    fetchStatus();

    pollIntervalRef.current = setInterval(() => {
      pollCountRef.current += 1;
      if (pollCountRef.current >= maxPolls) {
        if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
        setError("Polling timed out. Please refresh the page to check status.");
        return;
      }
      fetchStatus();
    }, 2500);

    return () => {
      isMountedRef.current = false;
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, [fetchStatus]);

  if (isLoading && !jobStatus) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-8 shadow-sm flex flex-col items-center justify-center space-y-4">
        <div className="w-8 h-8 border-4 border-indigo-600 border-t-transparent rounded-full animate-spin" />
        <p className="text-sm font-medium text-slate-600">Connecting to processing pipeline...</p>
      </div>
    );
  }

  const currentStageIndex = jobStatus?.stage
    ? STAGES.findIndex((s) => s.stage === jobStatus.stage)
    : -1;

  const isCompleted = jobStatus?.status === "COMPLETED";
  const isFailed = jobStatus?.status === "FAILED";

  const progressPercent = isCompleted
    ? 100
    : isFailed
    ? 100
    : currentStageIndex >= 0
    ? STAGES[currentStageIndex].percent
    : jobStatus?.status === "RUNNING"
    ? 25
    : 5;

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-6 sm:p-8 shadow-sm">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-6 border-b border-slate-100 gap-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">
            Meeting Pipeline Status
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Job ID: <span className="font-mono text-slate-600">{jobStatus?.job_id || meetingId}</span>
          </p>
        </div>

        <div className="flex items-center gap-2">
          {jobStatus?.status === "PENDING" && (
            <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-amber-100 text-amber-800">
              <span className="w-2 h-2 rounded-full bg-amber-500 mr-2 animate-ping" />
              Queued / Pending
            </span>
          )}
          {jobStatus?.status === "RUNNING" && (
            <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-indigo-100 text-indigo-800">
              <span className="w-2 h-2 rounded-full bg-indigo-600 mr-2 animate-pulse" />
              Processing ({jobStatus.stage || "RUNNING"})
            </span>
          )}
          {isCompleted && (
            <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800">
              <svg className="w-3.5 h-3.5 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
              </svg>
              Completed
            </span>
          )}
          {isFailed && (
            <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-red-100 text-red-800">
              <svg className="w-3.5 h-3.5 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
              </svg>
              Failed
            </span>
          )}
        </div>
      </div>

      {/* Progress Bar */}
      <div className="mt-6 mb-8">
        <div className="flex justify-between text-xs font-medium text-slate-600 mb-2">
          <span>Overall Pipeline Progress</span>
          <span>{progressPercent}%</span>
        </div>
        <div className="w-full bg-slate-100 rounded-full h-2.5 overflow-hidden">
          <div
            className={`h-2.5 rounded-full transition-all duration-500 ${
              isFailed ? "bg-red-500" : isCompleted ? "bg-emerald-500" : "bg-indigo-600"
            }`}
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      </div>

      {/* Stage Stepper */}
      <div className="space-y-4">
        {STAGES.map((s, idx) => {
          let state: "upcoming" | "current" | "done" | "failed" = "upcoming";

          if (isFailed && idx === currentStageIndex) {
            state = "failed";
          } else if (isCompleted || (currentStageIndex > -1 && idx < currentStageIndex)) {
            state = "done";
          } else if (idx === currentStageIndex) {
            state = "current";
          }

          return (
            <div
              key={s.stage}
              className={`flex items-start p-3.5 rounded-lg border transition-colors ${
                state === "current"
                  ? "bg-indigo-50/50 border-indigo-200"
                  : state === "done"
                  ? "bg-slate-50 border-slate-100 opacity-90"
                  : state === "failed"
                  ? "bg-red-50 border-red-200"
                  : "bg-white border-transparent text-slate-400"
              }`}
            >
              <div className="mr-3.5 mt-0.5 flex-shrink-0">
                {state === "done" && (
                  <div className="w-6 h-6 rounded-full bg-emerald-100 text-emerald-600 flex items-center justify-center">
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                    </svg>
                  </div>
                )}
                {state === "current" && (
                  <div className="w-6 h-6 rounded-full bg-indigo-600 text-white flex items-center justify-center animate-pulse">
                    <span className="w-2 h-2 rounded-full bg-white" />
                  </div>
                )}
                {state === "failed" && (
                  <div className="w-6 h-6 rounded-full bg-red-100 text-red-600 flex items-center justify-center">
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </div>
                )}
                {state === "upcoming" && (
                  <div className="w-6 h-6 rounded-full border-2 border-slate-200 text-slate-300 flex items-center justify-center text-xs font-semibold">
                    {idx + 1}
                  </div>
                )}
              </div>

              <div className="flex-1">
                <div className="flex items-center justify-between">
                  <h4
                    className={`text-sm font-medium ${
                      state === "current"
                        ? "text-indigo-950 font-semibold"
                        : state === "failed"
                        ? "text-red-900 font-semibold"
                        : state === "done"
                        ? "text-slate-800"
                        : "text-slate-400"
                    }`}
                  >
                    {s.label}
                  </h4>
                  {state === "current" && (
                    <span className="text-xs font-medium text-indigo-600 animate-pulse">In progress...</span>
                  )}
                </div>
                <p
                  className={`text-xs mt-0.5 ${
                    state === "current"
                      ? "text-indigo-700"
                      : state === "failed"
                      ? "text-red-600"
                      : "text-slate-500"
                  }`}
                >
                  {state === "failed" && jobStatus?.error_message ? jobStatus.error_message : s.desc}
                </p>
              </div>
            </div>
          );
        })}
      </div>

      {error && (
        <div className="mt-6 p-4 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700">
          {error}
        </div>
      )}
    </div>
  );
}

