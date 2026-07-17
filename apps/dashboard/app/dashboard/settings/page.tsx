"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { createClient } from "@/lib/supabase/client";

interface ClientSettings {
  business_name: string;
  email: string;
  phone: string | null;
  voice_sample: string | null;
  tier: string;
  subscription_status: string;
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<ClientSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordSaving, setPasswordSaving] = useState(false);
  const [passwordSaved, setPasswordSaved] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/settings")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => setSettings(d.client))
      .catch(() => setError("Could not load settings"));
  }, []);

  async function handleSetPassword() {
    setPasswordError(null);
    setPasswordSaved(false);
    if (newPassword.length < 8) {
      setPasswordError("Password must be at least 8 characters");
      return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordError("Passwords don't match");
      return;
    }
    setPasswordSaving(true);
    try {
      const supabase = createClient();
      const { error: updateError } = await supabase.auth.updateUser({ password: newPassword });
      if (updateError) throw updateError;
      setNewPassword("");
      setConfirmPassword("");
      setPasswordSaved(true);
      setTimeout(() => setPasswordSaved(false), 2000);
    } catch (err) {
      setPasswordError(err instanceof Error ? err.message : "Could not set password - please try again");
    } finally {
      setPasswordSaving(false);
    }
  }

  async function handleSave() {
    if (!settings) return;
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const response = await fetch("/api/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          business_name: settings.business_name,
          phone: settings.phone,
          voice_sample: settings.voice_sample,
        }),
      });
      if (!response.ok) throw new Error("Save failed");
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      setError("Could not save changes - please try again");
    } finally {
      setSaving(false);
    }
  }

  if (!settings) {
    return <p className="text-sm text-muted-foreground">{error ?? "Loading..."}</p>;
  }

  return (
    <div className="max-w-lg space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Firm Settings</h1>
        <p className="text-sm text-muted-foreground">
          Firm name, contact phone, and the writing style used to draft memos and letters in your voice.
        </p>
      </div>

      <Card>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="business_name">Firm name</Label>
            <Input
              id="business_name"
              value={settings.business_name}
              onChange={(e) => setSettings({ ...settings, business_name: e.target.value })}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input id="email" value={settings.email} disabled />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="phone">Phone</Label>
            <Input
              id="phone"
              value={settings.phone ?? ""}
              onChange={(e) => setSettings({ ...settings, phone: e.target.value })}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="voice_sample">
              Voice sample (3 sentences in your firm&apos;s own words)
            </Label>
            <Textarea
              id="voice_sample"
              rows={3}
              value={settings.voice_sample ?? ""}
              onChange={(e) => setSettings({ ...settings, voice_sample: e.target.value })}
              placeholder="Used to calibrate the tone of drafted advice memos and letters."
            />
          </div>

          <Separator />

          <div className="flex items-center justify-between">
            <div className="text-xs text-muted-foreground">
              Plan: <span className="font-medium text-foreground">{settings.tier}</span> ·{" "}
              {settings.subscription_status}
            </div>
            <div className="flex items-center gap-3">
              {saved && <span className="text-xs text-green-700">Saved</span>}
              {error && <span className="text-xs text-destructive">{error}</span>}
              <Button onClick={handleSave} disabled={saving}>
                {saving ? "Saving..." : "Save changes"}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-4">
          <div>
            <h2 className="text-sm font-semibold">Password</h2>
            <p className="text-xs text-muted-foreground">
              Set a password to sign in with your email and password next time, instead of a
              one-time email link.
            </p>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="new_password">New password</Label>
            <Input
              id="new_password"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="At least 8 characters"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="confirm_password">Confirm password</Label>
            <Input
              id="confirm_password"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
            />
          </div>

          <div className="flex items-center justify-end gap-3">
            {passwordSaved && <span className="text-xs text-green-700">Password set</span>}
            {passwordError && <span className="text-xs text-destructive">{passwordError}</span>}
            <Button
              onClick={handleSetPassword}
              disabled={passwordSaving || !newPassword || !confirmPassword}
            >
              {passwordSaving ? "Saving..." : "Set password"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
