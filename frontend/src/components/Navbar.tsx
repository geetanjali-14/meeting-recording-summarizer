"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearStoredToken, getStoredToken } from "@/lib/auth";

export function Navbar() {
  const [token, setToken] = useState<string | null>(null);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    setToken(getStoredToken());
  }, [pathname]);

  const handleLogout = () => {
    clearStoredToken();
    setToken(null);
    router.push("/login");
  };

  return (
    <header className="border-b border-slate-200 bg-white sticky top-0 z-30">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div className="flex items-center space-x-6">
          <Link
            href="/"
            className="text-lg font-bold tracking-tight text-slate-900 flex items-center space-x-2"
          >
            <span className="w-7 h-7 rounded-md bg-indigo-600 text-white flex items-center justify-center font-black text-sm">
              M
            </span>
            <span>Meeting Summarizer</span>
          </Link>
          <nav className="hidden md:flex space-x-4">
            <Link
              href="/dashboard"
              className={`text-sm font-medium px-3 py-1.5 rounded-md transition-colors ${
                pathname === "/dashboard"
                  ? "bg-slate-100 text-slate-900"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              Dashboard
            </Link>
            <Link
              href="/meetings/new"
              className={`text-sm font-medium px-3 py-1.5 rounded-md transition-colors ${
                pathname === "/meetings/new"
                  ? "bg-slate-100 text-slate-900"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              Upload Meeting
            </Link>
          </nav>
        </div>

        <div className="flex items-center space-x-3">
          {token ? (
            <button
              onClick={handleLogout}
              className="text-xs font-semibold px-3 py-1.5 rounded-md border border-slate-300 text-slate-700 hover:bg-slate-50 transition-colors"
            >
              Sign Out
            </button>
          ) : (
            <Link
              href="/login"
              className="text-xs font-semibold px-3 py-1.5 rounded-md bg-indigo-600 text-white hover:bg-indigo-700 transition-colors"
            >
              Sign In
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}

