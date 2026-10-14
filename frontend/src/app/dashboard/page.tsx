"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { MeetingListItem } from "@/types/api";

export default function DashboardPage() {
  const [meetings, setMeetings] = useState<MeetingListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    let isMounted = true;

    const init = async () => {
      const token = await getAccessToken();
      if (!isMounted) return;
      if (!token) {
        router.push("/login");
        return;
      }

      try {
        setLoading(true);
        setError(null);
        const res = await api.listMeetings();
        if (isMounted) {
          setMeetings(res.data || []);
        }
      } catch (err) {
        if (!isMounted) return;
        if (err instanceof ApiError && err.status === 401) {
          router.push("/login");
          return;
        }
        setError(
          err instanceof Error
            ? err.message
            : "Failed to load meetings. Make sure the backend server is running."
        );
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    };

    init();

    return () => {
      isMounted = false;
    };
  }, [router]);

  return (
    <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between pb-6 border-b border-slate-200 mb-8">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">
            Meetings Dashboard
          </h1>
          <p className="text-sm text-slate-600 mt-1">
            Review meeting recordings, monitor processing pipelines, and view AI summaries.
          </p>
        </div>
        <div className="mt-4 sm:mt-0">
          <Link
            href="/meetings/new"
            className="inline-flex items-center justify-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 transition-colors"
          >
            + Upload Recording
          </Link>
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center items-center py-24">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600" />
        </div>
      ) : error ? (
        <div className="bg-red-50 border border-red-200 text-red-700 p-4 rounded-lg text-sm">
          {error}
        </div>
      ) : meetings.length === 0 ? (
        <div className="text-center py-16 bg-white border border-slate-200 rounded-xl p-8">
          <div className="w-12 h-12 bg-slate-100 text-slate-400 rounded-full flex items-center justify-center mx-auto mb-3">
            📁
          </div>
          <h3 className="text-base font-semibold text-slate-800">No meeting recordings yet</h3>
          <p className="text-sm text-slate-500 mt-1 max-w-sm mx-auto">
            Upload an audio or video recording to begin automated speech-to-text, speaker
            diarization, and structured intelligence.
          </p>
          <div className="mt-6">
            <Link
              href="/meetings/new"
              className="inline-flex items-center px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 transition-colors"
            >
              Upload Your First Meeting
            </Link>
          </div>
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm">
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50">
              <tr>
                <th
                  scope="col"
                  className="px-6 py-3.5 text-left text-xs font-semibold text-slate-600 uppercase tracking-wider"
                >
                  Meeting Title
                </th>
                <th
                  scope="col"
                  className="px-6 py-3.5 text-left text-xs font-semibold text-slate-600 uppercase tracking-wider"
                >
                  Date
                </th>
                <th
                  scope="col"
                  className="px-6 py-3.5 text-left text-xs font-semibold text-slate-600 uppercase tracking-wider"
                >
                  Status
                </th>
                <th
                  scope="col"
                  className="px-6 py-3.5 text-right text-xs font-semibold text-slate-600 uppercase tracking-wider"
                >
                  Action
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 bg-white">
              {meetings.map((meeting) => (
                <tr key={meeting.meeting_id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-6 py-4 whitespace-nowrap">
                    <Link
                      href={`/meetings/${meeting.meeting_id}`}
                      className="text-sm font-semibold text-indigo-600 hover:text-indigo-900"
                    >
                      {meeting.title}
                    </Link>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-600">
                    {meeting.meeting_date}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-100 text-emerald-800">
                      {meeting.status}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                    <Link
                      href={`/meetings/${meeting.meeting_id}`}
                      className="text-slate-600 hover:text-slate-900 mr-4"
                    >
                      View Details →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}

