"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { Logo } from "@/components/Logo";

const BUSINESS_TYPES = [
  { value: "accounting", label: "Accounting / public practice" },
  { value: "financial_advice", label: "Financial advice" },
  { value: "legal", label: "Legal" },
  { value: "other", label: "Other" },
];

const STATES = ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"];

export default function SignupPage() {
  const [form, setForm] = useState({
    business_name: "",
    business_type: "accounting",
    email: "",
    suburb: "",
    state: "NSW",
  });
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function update(field: keyof typeof form) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      setForm((f) => ({ ...f, [field]: e.target.value }));
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const response = await fetch("/api/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });

      if (response.status === 409) {
        setError("An account with this email already exists - use the sign-in page instead.");
        return;
      }
      if (!response.ok) {
        throw new Error("Signup failed");
      }

      const supabase = createClient();
      const { error: otpError } = await supabase.auth.signInWithOtp({
        email: form.email,
        options: {
          emailRedirectTo: `${window.location.origin}/auth/callback`,
          shouldCreateUser: true,
        },
      });
      if (otpError) throw otpError;
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signup failed - please try again");
    } finally {
      setLoading(false);
    }
  }

  const inputClass =
    "w-full rounded-lg border border-input px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring";

  return (
    <main className="flex flex-1 items-center justify-center bg-muted px-4 py-8">
      <div className="w-full max-w-md space-y-6 rounded-xl border border-border bg-card p-8 shadow-sm animate-fade-in">
        <div className="flex justify-center">
          <Logo />
        </div>

        {sent ? (
          <div className="space-y-2 text-center">
            <p className="text-sm font-semibold">Your 30-day free trial is ready.</p>
            <p className="text-sm text-muted-foreground">
              Check your email for a sign-in link to get started - no credit card required.
            </p>
          </div>
        ) : (
          <>
            <div className="space-y-1 text-center">
              <h1 className="text-lg font-bold">Start your free trial</h1>
              <p className="text-sm text-muted-foreground">
                30 days, 100 research queries, 10 documents. No credit card.
              </p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">
                  Firm name
                </label>
                <input
                  required
                  value={form.business_name}
                  onChange={update("business_name")}
                  placeholder="Smith & Co Accountants"
                  className={inputClass}
                />
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">
                  Work email
                </label>
                <input
                  type="email"
                  required
                  value={form.email}
                  onChange={update("email")}
                  placeholder="you@firm.com.au"
                  className={inputClass}
                />
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">
                  Firm type
                </label>
                <select value={form.business_type} onChange={update("business_type")} className={inputClass}>
                  {BUSINESS_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-xs font-medium text-muted-foreground">
                    Suburb
                  </label>
                  <input
                    required
                    value={form.suburb}
                    onChange={update("suburb")}
                    placeholder="Parramatta"
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-muted-foreground">
                    State
                  </label>
                  <select value={form.state} onChange={update("state")} className={inputClass}>
                    {STATES.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {error && <p className="text-sm text-destructive">{error}</p>}

              <button
                type="submit"
                disabled={loading}
                className="w-full rounded-lg bg-primary py-2 text-sm font-semibold text-primary-foreground transition-all duration-200 hover:bg-accent disabled:opacity-50"
              >
                {loading ? "Creating your trial..." : "Start free trial"}
              </button>
            </form>
          </>
        )}

        <p className="text-center text-sm text-muted-foreground">
          Already have an account?{" "}
          <Link href="/login" className="font-semibold text-accent hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </main>
  );
}
