"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { SiteHeader } from "@/components/SiteHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

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
    return (e: React.ChangeEvent<HTMLInputElement>) =>
      setForm((f) => ({ ...f, [field]: e.target.value }));
  }

  function updateSelect(field: keyof typeof form) {
    return (value: string) => setForm((f) => ({ ...f, [field]: value }));
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

  return (
    <>
      <SiteHeader cta="signup" />
      <main className="flex flex-1 items-start justify-center bg-background px-4 py-16">
        <Card className="w-full max-w-md animate-fade-in">
          <CardHeader>
            <h1 className="text-lg font-semibold">Start your free trial</h1>
            <p className="text-sm text-muted-foreground">
              30 days, 100 research queries, 10 documents. No credit card.
            </p>
          </CardHeader>
          <CardContent className="space-y-4">
            {sent ? (
              <div className="space-y-1">
                <p className="text-sm font-semibold">Your 30-day free trial is ready.</p>
                <p className="text-sm text-muted-foreground">
                  Check your email for a sign-in link to get started - no credit card required.
                </p>
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="space-y-1.5">
                  <Label htmlFor="business_name">Firm name</Label>
                  <Input
                    id="business_name"
                    required
                    value={form.business_name}
                    onChange={update("business_name")}
                    placeholder="Smith & Co Accountants"
                  />
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="email">Work email</Label>
                  <Input
                    id="email"
                    type="email"
                    required
                    value={form.email}
                    onChange={update("email")}
                    placeholder="you@firm.com.au"
                  />
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="business_type">Firm type</Label>
                  <Select value={form.business_type} onValueChange={updateSelect("business_type")}>
                    <SelectTrigger id="business_type" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {BUSINESS_TYPES.map((t) => (
                        <SelectItem key={t.value} value={t.value}>
                          {t.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="suburb">Suburb</Label>
                    <Input
                      id="suburb"
                      required
                      value={form.suburb}
                      onChange={update("suburb")}
                      placeholder="Parramatta"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="state">State</Label>
                    <Select value={form.state} onValueChange={updateSelect("state")}>
                      <SelectTrigger id="state" className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {STATES.map((s) => (
                          <SelectItem key={s} value={s}>
                            {s}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                {error && <p className="text-sm text-destructive">{error}</p>}

                <Button type="submit" disabled={loading} className="w-full">
                  {loading ? "Creating your trial..." : "Start free trial"}
                </Button>
              </form>
            )}

            <p className="text-sm text-muted-foreground">
              Already have an account?{" "}
              <Link href="/login" className="font-medium text-accent hover:underline">
                Sign in
              </Link>
            </p>
          </CardContent>
        </Card>
      </main>
    </>
  );
}
