import Link from "next/link";

export default function HomePage() {
  return (
    <div className="max-w-6xl mx-auto py-12 px-4 sm:px-6 lg:px-8">
      {/* Hero Section */}
      <div className="text-center py-12 sm:py-16">
        <h1 className="text-4xl sm:text-5xl font-extrabold tracking-tight text-slate-900">
          Turn Meeting Recordings into{" "}
          <span className="text-indigo-600">Actionable Intelligence</span>
        </h1>
        <p className="mt-4 max-w-2xl mx-auto text-base sm:text-lg text-slate-600 leading-relaxed">
          Asynchronous transcription, speaker diarization, and hallucination-free
          structured intelligence powered by Groq Whisper and open-weights LLMs.
        </p>

        <div className="mt-8 flex justify-center gap-4">
          <Link
            href="/meetings/new"
            className="px-6 py-3 rounded-lg bg-indigo-600 text-white font-semibold text-sm shadow-sm hover:bg-indigo-700 transition-colors"
          >
            Upload Meeting
          </Link>
          <Link
            href="/dashboard"
            className="px-6 py-3 rounded-lg bg-white border border-slate-300 text-slate-700 font-semibold text-sm hover:bg-slate-50 transition-colors"
          >
            View Dashboard
          </Link>
        </div>
      </div>

      {/* Feature Highlights Grid */}
      <div className="mt-8 grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="p-6 rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="w-10 h-10 rounded-lg bg-indigo-100 text-indigo-600 flex items-center justify-center font-bold mb-4">
            🎙️
          </div>
          <h2 className="text-base font-semibold text-slate-900 mb-2">
            Direct Cloud Storage Uploads
          </h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            Recordings stream directly to Cloudflare R2 using pre-signed URLs. Zero API server load or memory bottlenecks.
          </p>
        </div>

        <div className="p-6 rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="w-10 h-10 rounded-lg bg-indigo-100 text-indigo-600 flex items-center justify-center font-bold mb-4">
            👥
          </div>
          <h2 className="text-base font-semibold text-slate-900 mb-2">
            Speaker Diarization
          </h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            State-of-the-art speaker separation with Pyannote. Easily label and map detected speakers to real teammate names.
          </p>
        </div>

        <div className="p-6 rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="w-10 h-10 rounded-lg bg-indigo-100 text-indigo-600 flex items-center justify-center font-bold mb-4">
            🔍
          </div>
          <h2 className="text-base font-semibold text-slate-900 mb-2">
            Evidence Grounding
          </h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            Every decision, action item, topic, and risk includes direct citation links that jump straight to the exact transcript timestamps.
          </p>
        </div>
      </div>
    </div>
  );
}
