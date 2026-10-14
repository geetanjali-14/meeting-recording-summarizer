"use client";

import React, { useEffect, useState, useMemo, useCallback } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import {
  MeetingDetail,
  TranscriptSegment,
  MeetingAnalysisData,
} from "@/types/api";
import ProcessingStatus from "@/components/ProcessingStatus";
import SpeakerMapper from "@/components/SpeakerMapper";
import TranscriptViewer from "@/components/TranscriptViewer";
import MeetingIntelligence from "@/components/MeetingIntelligence";
import MeetingChat from "@/components/MeetingChat";

export default function MeetingDetailPage() {
  const params = useParams();
  const router = useRouter();
  const meetingId = (params?.id as string) || "";

  const [meeting, setMeeting] = useState<MeetingDetail | null>(null);
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [analysis, setAnalysis] = useState<MeetingAnalysisData | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Synchronized state
  const [highlightedSegmentId, setHighlightedSegmentId] = useState<string | null>(null);
  const [speakerMapping, setSpeakerMapping] = useState<Record<string, string>>({});
  const [isExporting, setIsExporting] = useState<boolean>(false);

  // Auth protection guard
  useEffect(() => {
    let isMounted = true;
    getAccessToken().then((token) => {
      if (isMounted && !token) {
        router.push("/login");
      }
    });
    return () => {
      isMounted = false;
    };
  }, [router]);

  const handleExport = async (format: "markdown" | "json") => {
    if (!meetingId || isExporting) return;
    try {
      setIsExporting(true);
      const res = await api.exportMeeting(meetingId, format);
      const blob = new Blob([res.data.content], { type: res.data.content_type });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = res.data.filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to export meeting";
      alert(msg);
    } finally {
      setIsExporting(false);
    }
  };

  const fetchMeetingData = useCallback(async () => {
    if (!meetingId) return;
    try {
      setIsLoading(true);
      const meetingRes = await api.getMeeting(meetingId);
      setMeeting(meetingRes.data);

      if (meetingRes.data.job?.status === "COMPLETED") {
        // Fetch transcript and analysis in parallel
        const [transcriptRes, analysisRes] = await Promise.allSettled([
          api.getTranscript(meetingId),
          api.getAnalysis(meetingId),
        ]);

        if (transcriptRes.status === "fulfilled") {
          setSegments(transcriptRes.value.data.segments || []);
        }

        if (analysisRes.status === "fulfilled") {
          setAnalysis(analysisRes.value.data);
        }
      }
      setError(null);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      const msg = err instanceof Error ? err.message : "Failed to load meeting";
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [meetingId, router]);

  useEffect(() => {
    fetchMeetingData();
  }, [fetchMeetingData]);

  // Load saved speaker mapping from localStorage
  useEffect(() => {
    if (meetingId) {
      try {
        const saved = localStorage.getItem(`speaker_map_${meetingId}`);
        if (saved) {
          setSpeakerMapping(JSON.parse(saved));
        }
      } catch (e) {
        // ignore parse error
      }
    }
  }, [meetingId]);

  const handleSpeakerMappingChange = (newMapping: Record<string, string>) => {
    setSpeakerMapping(newMapping);
    try {
      localStorage.setItem(`speaker_map_${meetingId}`, JSON.stringify(newMapping));
    } catch (e) {
      // ignore storage error
    }
  };

  const detectedSpeakers = useMemo(() => {
    const speakers = new Set<string>();
    segments.forEach((seg) => {
      if (seg.speaker_label) {
        speakers.add(seg.speaker_label);
      } else if (seg.speaker) {
        speakers.add(seg.speaker);
      }
    });
    return Array.from(speakers).sort();
  }, [segments]);

  const handleEvidenceClick = (segmentId: string) => {
    setHighlightedSegmentId(segmentId);
  };

  if (isLoading && !meeting) {
    return (
      <div className="max-w-7xl mx-auto py-12 px-4 sm:px-6 lg:px-8">
        <div className="flex flex-col items-center justify-center p-12 bg-white rounded-xl border border-slate-200">
          <div className="w-8 h-8 border-4 border-indigo-600 border-t-transparent rounded-full animate-spin mb-4" />
          <p className="text-sm font-medium text-slate-600">Loading meeting details...</p>
        </div>
      </div>
    );
  }

  if (error && !meeting) {
    return (
      <div className="max-w-7xl mx-auto py-12 px-4 sm:px-6 lg:px-8">
        <div className="p-6 bg-red-50 rounded-xl border border-red-200 text-center">
          <p className="text-sm font-semibold text-red-800">{error}</p>
          <Link
            href="/dashboard"
            className="mt-4 inline-block text-xs font-semibold text-indigo-600 hover:underline"
          >
            ← Return to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  const isJobCompleted = meeting?.job?.status === "COMPLETED";

  return (
    <div className="max-w-7xl mx-auto py-8 px-4 sm:px-6 lg:px-8 space-y-6">
      {/* Top Header & Breadcrumb */}
      <div>
        <div className="flex items-center gap-2 text-xs text-slate-500 mb-2">
          <Link href="/dashboard" className="hover:text-slate-900 transition-colors">
            Dashboard
          </Link>
          <span>/</span>
          <span className="text-slate-800 font-medium">Meeting</span>
          <span>/</span>
          <span className="font-mono text-slate-400">{meetingId.slice(0, 8)}</span>
        </div>

        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">
              {meeting?.title || "Untitled Meeting"}
            </h1>
            <p className="text-xs text-slate-500 mt-1">
              Date: {meeting?.meeting_date} • Created:{" "}
              {meeting?.created_at ? new Date(meeting.created_at).toLocaleString() : "Unknown"}
            </p>
          </div>

          <div className="flex items-center gap-2">
            {isJobCompleted && (
              <div className="flex items-center gap-1.5 border border-slate-200 rounded-lg p-0.5 bg-white">
                <button
                  onClick={() => handleExport("markdown")}
                  disabled={isExporting}
                  className="text-xs font-medium text-slate-700 hover:text-indigo-600 px-2.5 py-1 rounded hover:bg-slate-50 transition-colors disabled:opacity-50"
                  title="Export meeting intelligence as formatted Markdown"
                >
                  📥 Export .md
                </button>
                <span className="text-slate-300">|</span>
                <button
                  onClick={() => handleExport("json")}
                  disabled={isExporting}
                  className="text-xs font-medium text-slate-700 hover:text-indigo-600 px-2.5 py-1 rounded hover:bg-slate-50 transition-colors disabled:opacity-50"
                  title="Export raw meeting intelligence as JSON"
                >
                  📥 Export .json
                </button>
              </div>
            )}
            <button
              onClick={() => fetchMeetingData()}
              className="text-xs font-medium text-slate-600 hover:text-slate-900 bg-white border border-slate-200 px-3 py-1.5 rounded-lg hover:bg-slate-50 transition-colors"
            >
              ↻ Refresh
            </button>
            <Link
              href="/meetings/new"
              className="text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-700 px-3.5 py-1.5 rounded-lg transition-colors"
            >
              + Upload Another
            </Link>
          </div>
        </div>
      </div>

      {/* If Meeting job is not yet COMPLETED */}
      {!isJobCompleted && (
        <ProcessingStatus
          meetingId={meetingId}
          onCompleted={() => {
            fetchMeetingData();
          }}
          onFailed={(err) => {
            setError(err);
          }}
        />
      )}

      {/* If Meeting is COMPLETED, show intelligence and transcript */}
      {isJobCompleted && (
        <>
          {/* Speaker Mapper Bar */}
          <SpeakerMapper
            detectedSpeakers={detectedSpeakers}
            speakerMapping={speakerMapping}
            onMappingChange={handleSpeakerMappingChange}
          />

          {/* Dual Panel Layout: Intelligence (Left) & Transcript (Right) */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
            {/* Left Column: Structured Intelligence & Interactive Q&A */}
            <div className="lg:col-span-7 space-y-6">
              {analysis ? (
                <MeetingIntelligence
                  analysis={analysis}
                  onSelectSegment={handleEvidenceClick}
                  activeSegmentId={highlightedSegmentId}
                />
              ) : (
                <div className="bg-white rounded-xl border border-slate-200 p-8 text-center text-slate-500">
                  <p className="text-sm">Analysis results are not yet available.</p>
                </div>
              )}

              {/* Conversational Q&A Panel */}
              <MeetingChat
                meetingId={meetingId}
                onSelectSegment={handleEvidenceClick}
              />
            </div>

            {/* Right Column: Synchronized Transcript */}
            <div className="lg:col-span-5 sticky top-20">
              <TranscriptViewer
                segments={segments}
                highlightedSegmentId={highlightedSegmentId}
                speakerMapping={speakerMapping}
                onSelectSegment={(id) => setHighlightedSegmentId(id)}
              />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

