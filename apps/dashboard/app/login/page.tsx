"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { startDemoLogin } from "@/lib/demo-login";
import { SiteHeader } from "@/components/SiteHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
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
      setError(err instanceof Error ? err.message : "Failed to send sign-in link");
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
              We&apos;ll email you a secure sign-in link.
            </p>
          </CardHeader>
          <CardContent className="space-y-4">
            {sent ? (
              <p className="text-sm text-muted-foreground">
                Check your email for a sign-in link.
              </p>
            ) : (
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
                {error && <p className="text-sm text-destructive">{error}</p>}
                <Button
                  type="submit"
                  disabled={loading}
                  className="w-full"
                >
                  {loading ? "Sending..." : "Send sign-in link"}
                </Button>
              </form>
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
