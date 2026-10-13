"use client";

import React, { useState } from "react";
import {
  MeetingAnalysisData,
  DecisionItem,
  ActionItem,
  TopicItem,
  RiskItem,
  OpenQuestionItem,
} from "@/types/api";
import EvidenceBadge from "./EvidenceBadge";

interface MeetingIntelligenceProps {
  analysis: MeetingAnalysisData;
  onSelectSegment?: (segmentId: string) => void;
  activeSegmentId?: string | null;
}

export default function MeetingIntelligence({
  analysis,
  onSelectSegment,
  activeSegmentId,
}: MeetingIntelligenceProps) {
  const [activeTab, setActiveTab] = useState<
    "overview" | "decisions" | "actions" | "topics" | "risks"
  >("overview");

  const {
    executive_summary,
    topics,
    decisions,
    action_items,
    risks,
    open_questions,
    model,
    estimated_cost_usd,
  } = analysis;

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm flex flex-col">
      {/* Header with Navigation Tabs */}
      <div className="px-5 pt-4 border-b border-slate-100">
        <div className="flex items-center justify-between pb-3">
          <h2 className="text-base font-semibold text-slate-900 flex items-center gap-2">
            <span>Meeting Intelligence</span>
            <span className="text-[11px] font-mono font-normal text-slate-400 bg-slate-100 px-2 py-0.5 rounded">
              {model}
              {estimated_cost_usd !== null && estimated_cost_usd !== undefined && (
                <span className="ml-1.5 opacity-80">(${(estimated_cost_usd).toFixed(4)})</span>
              )}
            </span>
          </h2>
        </div>

        <div className="flex space-x-1 sm:space-x-4 overflow-x-auto text-xs font-medium border-b border-transparent -mb-px">
          {[
            { id: "overview", label: "Executive Summary", count: null },
            { id: "decisions", label: "Decisions", count: decisions?.length },
            { id: "actions", label: "Action Items", count: action_items?.length },
            { id: "topics", label: "Topics", count: topics?.length },
            { id: "risks", label: "Risks & Questions", count: (risks?.length || 0) + (open_questions?.length || 0) },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as typeof activeTab)}
              className={`pb-3 px-2 border-b-2 font-medium flex items-center gap-1.5 whitespace-nowrap transition-colors ${
                activeTab === tab.id
                  ? "border-indigo-600 text-indigo-600 font-semibold"
                  : "border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300"
              }`}
            >
              <span>{tab.label}</span>
              {tab.count !== null && tab.count !== undefined && (
                <span
                  className={`px-1.5 py-0.2 rounded-full text-[10px] ${
                    activeTab === tab.id
                      ? "bg-indigo-100 text-indigo-700"
                      : "bg-slate-100 text-slate-600"
                  }`}
                >
                  {tab.count}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Tab Content Panes */}
      <div className="p-5 overflow-y-auto max-h-[600px]">
        {/* Executive Summary */}
        {activeTab === "overview" && (
          <div className="space-y-6">
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">
                Executive Summary
              </h3>
              <p className="text-sm text-slate-800 leading-relaxed bg-slate-50/60 p-4 rounded-lg border border-slate-100 whitespace-pre-line">
                {executive_summary || "No executive summary available."}
              </p>
            </div>

            {/* Quick KPI stats */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="p-3 bg-slate-50 rounded-lg border border-slate-100 text-center">
                <span className="block text-2xl font-bold text-slate-900">
                  {decisions?.length || 0}
                </span>
                <span className="text-xs text-slate-500 font-medium">Decisions Made</span>
              </div>
              <div className="p-3 bg-slate-50 rounded-lg border border-slate-100 text-center">
                <span className="block text-2xl font-bold text-indigo-600">
                  {action_items?.length || 0}
                </span>
                <span className="text-xs text-slate-500 font-medium">Action Items</span>
              </div>
              <div className="p-3 bg-slate-50 rounded-lg border border-slate-100 text-center">
                <span className="block text-2xl font-bold text-slate-900">
                  {topics?.length || 0}
                </span>
                <span className="text-xs text-slate-500 font-medium">Key Topics</span>
              </div>
              <div className="p-3 bg-slate-50 rounded-lg border border-slate-100 text-center">
                <span className="block text-2xl font-bold text-amber-600">
                  {risks?.length || 0}
                </span>
                <span className="text-xs text-slate-500 font-medium">Risks Flagged</span>
              </div>
            </div>
          </div>
        )}

        {/* Decisions */}
        {activeTab === "decisions" && (
          <div className="space-y-3">
            {(!decisions || decisions.length === 0) ? (
              <p className="text-sm text-slate-500 text-center py-6">
                No decisions recorded for this meeting.
              </p>
            ) : (
              decisions.map((dec: DecisionItem) => (
                <div
                  key={dec.decision_id}
                  className="p-3.5 rounded-lg border border-slate-200 bg-white hover:border-slate-300 transition-colors"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <span
                          className={`text-[10px] font-semibold px-2 py-0.5 rounded-full uppercase tracking-wider ${
                            dec.confidence === "EXPLICIT"
                              ? "bg-emerald-100 text-emerald-800 border border-emerald-200"
                              : "bg-blue-100 text-blue-800 border border-blue-200"
                          }`}
                        >
                          {dec.confidence || "EXPLICIT"}
                        </span>
                      </div>
                      <p className="text-sm font-medium text-slate-900">
                        {dec.decision_text}
                      </p>
                    </div>
                  </div>
                  <EvidenceBadge
                    segmentIds={dec.evidence_segment_ids}
                    onSelectSegment={onSelectSegment}
                    activeSegmentId={activeSegmentId}
                  />
                </div>
              ))
            )}
          </div>
        )}

        {/* Action Items */}
        {activeTab === "actions" && (
          <div className="space-y-3">
            {(!action_items || action_items.length === 0) ? (
              <p className="text-sm text-slate-500 text-center py-6">
                No action items recorded for this meeting.
              </p>
            ) : (
              action_items.map((action: ActionItem) => (
                <div
                  key={action.action_item_id}
                  className="p-3.5 rounded-lg border border-slate-200 bg-white hover:border-slate-300 transition-colors"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1">
                      <p className="text-sm font-medium text-slate-900">
                        {action.action_text}
                      </p>
                      <div className="flex flex-wrap items-center gap-2 mt-1.5 text-xs">
                        <span className="inline-flex items-center px-2 py-0.5 rounded bg-slate-100 text-slate-700 font-medium">
                          👤 Owner: {action.owner || "Unassigned"}
                        </span>
                        {action.due_date && (
                          <span className="inline-flex items-center px-2 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200 font-medium">
                            📅 Due: {action.due_date}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                  <EvidenceBadge
                    segmentIds={action.evidence_segment_ids}
                    onSelectSegment={onSelectSegment}
                    activeSegmentId={activeSegmentId}
                  />
                </div>
              ))
            )}
          </div>
        )}

        {/* Key Topics */}
        {activeTab === "topics" && (
          <div className="space-y-3">
            {(!topics || topics.length === 0) ? (
              <p className="text-sm text-slate-500 text-center py-6">
                No key topics recorded for this meeting.
              </p>
            ) : (
              topics.map((topic: TopicItem) => (
                <div
                  key={topic.topic_id}
                  className="p-3.5 rounded-lg border border-slate-200 bg-white hover:border-slate-300 transition-colors"
                >
                  <h4 className="text-sm font-semibold text-slate-900">
                    {topic.title}
                  </h4>
                  {topic.summary && (
                    <p className="text-xs text-slate-600 mt-1 leading-relaxed">
                      {topic.summary}
                    </p>
                  )}
                </div>
              ))
            )}
          </div>
        )}

        {/* Risks & Questions */}
        {activeTab === "risks" && (
          <div className="space-y-6">
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">
                Identified Risks ({risks?.length || 0})
              </h4>
              {(!risks || risks.length === 0) ? (
                <p className="text-xs text-slate-500 italic bg-slate-50 p-3 rounded">
                  No risks identified.
                </p>
              ) : (
                <div className="space-y-2">
                  {risks.map((risk: RiskItem) => (
                    <div
                      key={risk.risk_id}
                      className="p-3 rounded-lg border border-amber-200 bg-amber-50/40"
                    >
                      <p className="text-xs font-semibold text-amber-950">
                        {risk.risk_text}
                      </p>
                      <EvidenceBadge
                        segmentIds={risk.evidence_segment_ids}
                        onSelectSegment={onSelectSegment}
                        activeSegmentId={activeSegmentId}
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">
                Open Questions ({open_questions?.length || 0})
              </h4>
              {(!open_questions || open_questions.length === 0) ? (
                <p className="text-xs text-slate-500 italic bg-slate-50 p-3 rounded">
                  No open questions remaining.
                </p>
              ) : (
                <div className="space-y-2">
                  {open_questions.map((q: OpenQuestionItem) => (
                    <div
                      key={q.question_id}
                      className="p-3 rounded-lg border border-slate-200 bg-slate-50/60"
                    >
                      <p className="text-xs font-medium text-slate-800">
                        ❓ {q.question_text}
                      </p>
                      <EvidenceBadge
                        segmentIds={q.evidence_segment_ids}
                        onSelectSegment={onSelectSegment}
                        activeSegmentId={activeSegmentId}
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

