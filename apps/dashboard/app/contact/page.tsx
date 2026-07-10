"use client";

import { useState, type FormEvent } from "react";
import { MarketingHeader } from "@/components/MarketingHeader";
import { MarketingFooter } from "@/components/MarketingFooter";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

export default function ContactPage() {
  const [form, setForm] = useState({ name: "", email: "", firm_name: "", message: "" });
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function update(field: keyof typeof form) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm((f) => ({ ...f, [field]: e.target.value }));
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/contact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!response.ok) throw new Error("Failed");
      setSent(true);
    } catch {
      setError("Could not send your message - please try again or email us directly.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <MarketingHeader />
      <main className="flex-1 bg-background px-6 py-20">
        <div className="mx-auto max-w-lg">
          <h1 className="mb-2 text-3xl font-bold text-foreground md:text-4xl">Get in touch</h1>
          <p className="mb-10 text-lg text-muted-foreground">
            Questions about pricing, a feature, or just want to talk to a person - send us a
            message and we&apos;ll get back to you.
          </p>

          <Card>
            <CardHeader />
            <CardContent>
              {sent ? (
                <p className="text-sm text-muted-foreground">
                  Thanks - we&apos;ve got your message and will reply soon.
                </p>
              ) : (
                <form onSubmit={handleSubmit} className="space-y-4">
                  <div className="space-y-1.5">
                    <Label htmlFor="name">Name</Label>
                    <Input id="name" required value={form.name} onChange={update("name")} />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="email">Email</Label>
                    <Input
                      id="email"
                      type="email"
                      required
                      value={form.email}
                      onChange={update("email")}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="firm_name">Firm name (optional)</Label>
                    <Input id="firm_name" value={form.firm_name} onChange={update("firm_name")} />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="message">Message</Label>
                    <Textarea id="message" rows={4} required value={form.message} onChange={update("message")} />
                  </div>
                  {error && <p className="text-sm text-destructive">{error}</p>}
                  <Button type="submit" disabled={loading} className="w-full">
                    {loading ? "Sending..." : "Send message"}
                  </Button>
                </form>
              )}
            </CardContent>
          </Card>
        </div>
      </main>
      <MarketingFooter />
    </>
  );
}
