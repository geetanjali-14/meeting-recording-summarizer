export default function HomePage() {
  return (
    <main className="min-h-screen p-8 max-w-4xl mx-auto">
      <header className="border-b pb-4 mb-8">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">
          Meeting Intelligence Summarizer
        </h1>
        <p className="text-slate-600 mt-2">
          Asynchronous meeting transcription, diarization, and structured intelligence.
        </p>
      </header>

      <section className="bg-white rounded-lg shadow-sm border border-slate-200 p-6">
        <h2 className="text-xl font-semibold text-slate-800 mb-2">
          Phase 1 System Scaffolding
        </h2>
        <p className="text-slate-600">
          Backend API and Next.js frontend are configured. Health status and environment contracts are established.
        </p>
      </section>
    </main>
  );
}

