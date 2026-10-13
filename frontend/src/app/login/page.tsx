"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { setStoredToken } from "@/lib/auth";

export default function LoginPage() {
  const [tokenInput, setTokenInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  const handleLogin = (e: FormEvent) => {
    e.preventDefault();
    if (!tokenInput.trim()) {
      setError("Please provide a valid JWT access token.");
      return;
    }
    setStoredToken(tokenInput.trim());
    router.push("/dashboard");
  };

  return (
    <main className="min-h-[80vh] flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-white border border-slate-200 rounded-xl shadow-sm p-8">
        <div className="mb-6 text-center">
          <div className="w-10 h-10 rounded-lg bg-indigo-600 text-white font-bold text-lg flex items-center justify-center mx-auto mb-3">
            M
          </div>
          <h1 className="text-2xl font-bold text-slate-900">Sign in to your account</h1>
          <p className="text-sm text-slate-600 mt-1">
            Authenticate using your Supabase or service JWT bearer token.
          </p>
        </div>

        {error && (
          <div className="mb-4 p-3 text-xs bg-red-50 border border-red-200 text-red-700 rounded-md">
            {error}
          </div>
        )}

        <form onSubmit={handleLogin} className="space-y-4">
          <div>
            <label
              htmlFor="jwt-token"
              className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1"
            >
              JWT Bearer Token
            </label>
            <textarea
              id="jwt-token"
              rows={4}
              required
              value={tokenInput}
              onChange={(e) => setTokenInput(e.target.value)}
              placeholder="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-xs font-mono text-slate-800 placeholder-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          <button
            type="submit"
            className="w-full py-2.5 px-4 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold rounded-md shadow-sm transition-colors"
          >
            Authenticate & Continue
          </button>
        </form>

        <p className="mt-6 text-center text-xs text-slate-500">
          In local development, any valid test JWT or mock bearer token is accepted.
        </p>
      </div>
    </main>
  );
}

