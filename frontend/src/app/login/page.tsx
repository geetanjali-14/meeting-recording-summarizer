"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";
import { getAccessToken } from "@/lib/auth";

type AuthStep = "email" | "otp";

export default function LoginPage() {
  const [step, setStep] = useState<AuthStep>("email");
  const [email, setEmail] = useState("");
  const [otpToken, setOtpToken] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [infoMessage, setInfoMessage] = useState<string | null>(null);
  const [resendCooldown, setResendCooldown] = useState(0);

  const router = useRouter();

  // Redirect if already authenticated
  useEffect(() => {
    let isMounted = true;
    getAccessToken().then((token) => {
      if (isMounted && token) {
        router.push("/dashboard");
      }
    });
    return () => {
      isMounted = false;
    };
  }, [router]);

  // Resend cooldown timer
  useEffect(() => {
    if (resendCooldown <= 0) return;
    const timer = setInterval(() => {
      setResendCooldown((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, [resendCooldown]);

  // 1. Send OTP to user's email
  const handleSendOtp = async (e?: FormEvent) => {
    if (e) e.preventDefault();
    const cleanEmail = email.trim();
    if (!cleanEmail || !cleanEmail.includes("@")) {
      setError("Please provide a valid email address.");
      return;
    }

    try {
      setLoading(true);
      setError(null);
      setInfoMessage(null);

      const { error: otpError } = await supabase.auth.signInWithOtp({
        email: cleanEmail,
        options: {
          shouldCreateUser: true, // Auto-register new users
        },
      });

      if (otpError) {
        setError(otpError.message || "Failed to send verification code. Please try again.");
        return;
      }

      setStep("otp");
      setInfoMessage(`We sent a 6-digit verification code to ${cleanEmail}.`);
      setResendCooldown(60); // 60s cooldown
    } catch (err) {
      setError(err instanceof Error ? err.message : "An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  };

  // 2. Verify OTP code
  const handleVerifyOtp = async (e: FormEvent) => {
    e.preventDefault();
    const cleanToken = otpToken.trim();
    if (!cleanToken) {
      setError("Please enter the verification code from your email.");
      return;
    }

    try {
      setLoading(true);
      setError(null);

      const { data, error: verifyError } = await supabase.auth.verifyOtp({
        email: email.trim(),
        token: cleanToken,
        type: "email",
      });

      if (verifyError) {
        if (
          verifyError.message.toLowerCase().includes("expired") ||
          verifyError.message.toLowerCase().includes("invalid")
        ) {
          setError("The code entered is invalid or has expired. Please check or request a new code.");
        } else {
          setError(verifyError.message || "Verification failed. Please try again.");
        }
        return;
      }

      if (data.session) {
        router.push("/dashboard");
      } else {
        setError("Verification succeeded but no active session was established. Please retry.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  };

  const handleEditEmail = () => {
    setStep("email");
    setOtpToken("");
    setError(null);
    setInfoMessage(null);
  };

  return (
    <main className="min-h-[80vh] flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-white border border-slate-200 rounded-xl shadow-sm p-8">
        <div className="mb-6 text-center">
          <div className="w-10 h-10 rounded-lg bg-indigo-600 text-white font-bold text-lg flex items-center justify-center mx-auto mb-3">
            M
          </div>
          <h1 className="text-2xl font-bold text-slate-900">
            {step === "email" ? "Sign in to your account" : "Enter verification code"}
          </h1>
          <p className="text-sm text-slate-600 mt-1">
            {step === "email"
              ? "Passwordless sign-in with a one-time verification code."
              : `Check your inbox at ${email}`}
          </p>
        </div>

        {error && (
          <div
            role="alert"
            className="mb-4 p-3 text-xs bg-red-50 border border-red-200 text-red-700 rounded-md"
          >
            {error}
          </div>
        )}

        {infoMessage && (
          <div
            role="status"
            className="mb-4 p-3 text-xs bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-md"
          >
            {infoMessage}
          </div>
        )}

        {step === "email" ? (
          /* Step 1: Email Entry */
          <form onSubmit={handleSendOtp} className="space-y-4">
            <div>
              <label
                htmlFor="user-email"
                className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1"
              >
                Email Address
              </label>
              <input
                id="user-email"
                type="email"
                required
                disabled={loading}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@company.com"
                autoComplete="email"
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:opacity-50"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 px-4 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold rounded-md shadow-sm transition-colors disabled:opacity-60 flex items-center justify-center space-x-2"
            >
              {loading ? (
                <span>Sending code...</span>
              ) : (
                <span>Send verification code</span>
              )}
            </button>
          </form>
        ) : (
          /* Step 2: OTP Verification */
          <form onSubmit={handleVerifyOtp} className="space-y-4">
            <div>
              <div className="flex items-center justify-between mb-1">
                <label
                  htmlFor="otp-code"
                  className="block text-xs font-semibold uppercase tracking-wider text-slate-700"
                >
                  6-Digit Verification Code
                </label>
                <button
                  type="button"
                  onClick={handleEditEmail}
                  className="text-xs text-indigo-600 hover:text-indigo-800 underline"
                >
                  Change email
                </button>
              </div>
              <input
                id="otp-code"
                type="text"
                required
                maxLength={8}
                disabled={loading}
                value={otpToken}
                onChange={(e) => setOtpToken(e.target.value.trim())}
                placeholder="123456"
                autoFocus
                autoComplete="one-time-code"
                inputMode="numeric"
                className="w-full rounded-md border border-slate-300 px-3 py-2.5 text-center text-lg font-mono tracking-widest text-slate-900 placeholder-slate-300 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:opacity-50"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 px-4 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold rounded-md shadow-sm transition-colors disabled:opacity-60 flex items-center justify-center space-x-2"
            >
              {loading ? (
                <span>Verifying...</span>
              ) : (
                <span>Verify and continue</span>
              )}
            </button>

            <div className="pt-2 text-center">
              {resendCooldown > 0 ? (
                <p className="text-xs text-slate-500">
                  Resend code in {resendCooldown}s
                </p>
              ) : (
                <button
                  type="button"
                  disabled={loading}
                  onClick={() => handleSendOtp()}
                  className="text-xs text-indigo-600 hover:text-indigo-800 font-medium"
                >
                  Didn’t receive a code? Resend code
                </button>
              )}
            </div>
          </form>
        )}

        <p className="mt-6 text-center text-xs text-slate-500">
          No password needed. New accounts are created automatically upon verification.
        </p>
      </div>
    </main>
  );
}
