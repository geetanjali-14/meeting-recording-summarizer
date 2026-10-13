"use client";

import React, { useState, useEffect, useRef } from "react";
import { api } from "@/lib/api";
import { ChatMessageItem, ChatCitation } from "@/types/api";

interface MeetingChatProps {
  meetingId: string;
  onSelectSegment: (segmentId: string) => void;
}

export default function MeetingChat({ meetingId, onSelectSegment }: MeetingChatProps) {
  const [messages, setMessages] = useState<ChatMessageItem[]>([]);
  const [question, setQuestion] = useState("");
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    async function loadHistory() {
      try {
        const res = await api.getChatMessages(meetingId);
        if (res.data && res.data.length > 0) {
          setMessages(res.data);
          setSessionId(res.data[0].session_id);
        }
      } catch (err) {
        // Chat history is optional
      }
    }
    loadHistory();
  }, [meetingId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim() || isLoading) return;

    const userText = question.trim();
    setQuestion("");
    setError(null);

    // Optimistic user message
    const tempUserMsg: ChatMessageItem = {
      message_id: "temp-" + Date.now(),
      session_id: sessionId || "new",
      meeting_id: meetingId,
      role: "USER",
      content: userText,
      citations: [],
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMsg]);
    setIsLoading(true);

    try {
      const res = await api.sendChatMessage(meetingId, userText, sessionId);
      setSessionId(res.data.session_id);
      setMessages((prev) => [...prev, res.data.message]);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to get answer";
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  };

  const formatTimestamp = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  };

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm flex flex-col h-[520px]">
      {/* Header */}
      <div className="p-4 border-b border-slate-100 flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-900 flex items-center gap-2">
            <span>💬</span> Meeting Q&A
          </h2>
          <p className="text-xs text-slate-500">
            Ask questions grounded strictly in the meeting transcript dialogue
          </p>
        </div>
      </div>

      {/* Messages Scroll Area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center py-12 text-slate-400 text-sm">
            <p className="text-2xl mb-2">💡</p>
            <p>No questions yet.</p>
            <p className="text-xs mt-1 text-slate-400">
              Try asking: &quot;What decisions were made regarding the database?&quot;
            </p>
          </div>
        )}

        {messages.map((m) => (
          <div
            key={m.message_id}
            className={`flex flex-col ${
              m.role === "USER" ? "items-end" : "items-start"
            }`}
          >
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm ${
                m.role === "USER"
                  ? "bg-indigo-600 text-white rounded-br-none"
                  : "bg-slate-100 text-slate-800 rounded-bl-none"
              }`}
            >
              <p className="whitespace-pre-wrap">{m.content}</p>

              {/* Grounded Citations */}
              {m.citations && m.citations.length > 0 && (
                <div className="mt-2.5 pt-2 border-t border-slate-200/60 flex flex-wrap gap-1.5 items-center">
                  <span className="text-[11px] font-medium text-slate-500 mr-1">
                    Citations:
                  </span>
                  {m.citations.map((c: ChatCitation) => (
                    <button
                      key={c.segment_id}
                      onClick={() => onSelectSegment(c.segment_id)}
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-mono font-medium bg-white text-indigo-700 border border-indigo-200 hover:bg-indigo-50 hover:border-indigo-300 transition-colors shadow-2xs"
                      title={c.text_snippet || `Jump to segment`}
                    >
                      <span>⏱</span>
                      <span>
                        {formatTimestamp(c.start_time)} - {formatTimestamp(c.end_time)}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {isLoading && (
          <div className="flex items-center gap-2 text-slate-400 text-xs py-2">
            <span className="animate-spin">⏳</span>
            <span>Searching transcript & formulating answer...</span>
          </div>
        )}

        {error && (
          <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs">
            {error}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Form */}
      <form onSubmit={handleSubmit} className="p-3 border-t border-slate-100 flex gap-2">
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask a question about this meeting..."
          disabled={isLoading}
          className="flex-1 text-sm bg-slate-50 border border-slate-200 rounded-lg px-3.5 py-2 text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:bg-white transition-all disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={isLoading || !question.trim()}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg disabled:opacity-50 transition-colors flex items-center gap-1.5"
        >
          <span>Ask</span>
          <span>→</span>
        </button>
      </form>
    </div>
  );
}

