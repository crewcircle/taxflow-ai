"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { startDemoLogin } from "@/lib/demo-login";
import { SiteHeader } from "@/components/SiteHeader";
import { GoogleSignInButton } from "@/components/GoogleSignInButton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"magic" | "password">("magic");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [demoLoading, setDemoLoading] = useState(false);

  async function handleDemoLogin() {
    setDemoLoading(true);
    setError(null);
    const result = await startDemoLogin();
    if (result.ok) {
      router.push("/dashboard");
    } else {
      setError(result.error);
      setDemoLoading(false);
    }
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const supabase = createClient();
      if (mode === "password") {
        const { error: signInError } = await supabase.auth.signInWithPassword({ email, password });
        if (signInError) throw signInError;
        router.push("/dashboard");
        return;
      }
      const { error: signInError } = await supabase.auth.signInWithOtp({
        email,
        options: {
          emailRedirectTo: `${window.location.origin}/auth/callback`,
          shouldCreateUser: true,
        },
      });
      if (signInError) throw signInError;
      setSent(true);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : mode === "password"
            ? "Incorrect email or password"
            : "Failed to send sign-in link"
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <SiteHeader cta="login" />
      <main className="flex flex-1 items-start justify-center bg-background px-4 py-24">
        <Card className="w-full max-w-sm animate-fade-in">
          <CardHeader>
            <h1 className="text-lg font-semibold">Sign in to TaxFlow</h1>
            <p className="text-sm text-muted-foreground">
              {mode === "password"
                ? "Sign in with your email and password."
                : "We'll email you a secure sign-in link."}
            </p>
          </CardHeader>
          <CardContent className="space-y-4">
            {sent ? (
              <p className="text-sm text-muted-foreground">
                Check your email for a sign-in link.
              </p>
            ) : (
              <>
                <GoogleSignInButton />

                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Separator className="flex-1" />
                  or
                  <Separator className="flex-1" />
                </div>

                <div className="flex gap-1 rounded-lg bg-muted p-1 text-sm">
                  <button
                    type="button"
                    onClick={() => {
                      setMode("magic");
                      setError(null);
                    }}
                    className={`flex-1 rounded-md py-1.5 font-medium transition-colors ${
                      mode === "magic" ? "bg-background shadow-sm" : "text-muted-foreground"
                    }`}
                  >
                    Email link
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setMode("password");
                      setError(null);
                    }}
                    className={`flex-1 rounded-md py-1.5 font-medium transition-colors ${
                      mode === "password" ? "bg-background shadow-sm" : "text-muted-foreground"
                    }`}
                  >
                    Password
                  </button>
                </div>

                <form onSubmit={handleSubmit} className="space-y-4">
                  <div className="space-y-1.5">
                    <Label htmlFor="email">Work email</Label>
                    <Input
                      id="email"
                      type="email"
                      required
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="you@firm.com.au"
                    />
                  </div>
                  {mode === "password" && (
                    <div className="space-y-1.5">
                      <Label htmlFor="password">Password</Label>
                      <Input
                        id="password"
                        type="password"
                        required
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                      />
                    </div>
                  )}
                  {error && <p className="text-sm text-destructive">{error}</p>}
                  <Button type="submit" disabled={loading} className="w-full">
                    {loading
                      ? mode === "password"
                        ? "Signing in..."
                        : "Sending..."
                      : mode === "password"
                        ? "Sign in"
                        : "Send sign-in link"}
                  </Button>
                </form>
              </>
            )}

            <p className="text-sm text-muted-foreground">
              New to TaxFlow?{" "}
              <Link href="/signup" className="font-medium text-accent hover:underline">
                Start your free trial
              </Link>
            </p>

            <Separator />

            <Button
              type="button"
              variant="outline"
              className="w-full"
              disabled={demoLoading}
              onClick={handleDemoLogin}
            >
              {demoLoading ? "Loading demo..." : "Try the live demo - no signup"}
            </Button>
          </CardContent>
        </Card>
      </main>
    </>
  );
}
