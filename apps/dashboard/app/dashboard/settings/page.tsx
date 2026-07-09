"use client";

import { useEffect, useState } from "react";

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

  useEffect(() => {
    fetch("/api/settings")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => setSettings(d.client))
      .catch(() => setError("Could not load settings"));
  }, []);

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

  const inputClass =
    "w-full rounded-lg border border-input px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring";

  return (
    <div className="max-w-lg space-y-6">
      <h1 className="text-xl font-semibold">Firm Settings</h1>

      <div className="space-y-4 rounded-lg border border-border p-4">
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">Firm name</label>
          <input
            value={settings.business_name}
            onChange={(e) => setSettings({ ...settings, business_name: e.target.value })}
            className={inputClass}
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">Email</label>
          <input value={settings.email} disabled className={`${inputClass} bg-muted text-muted-foreground`} />
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">Phone</label>
          <input
            value={settings.phone ?? ""}
            onChange={(e) => setSettings({ ...settings, phone: e.target.value })}
            className={inputClass}
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            Voice sample (3 sentences in your firm&apos;s own words)
          </label>
          <textarea
            rows={3}
            value={settings.voice_sample ?? ""}
            onChange={(e) => setSettings({ ...settings, voice_sample: e.target.value })}
            placeholder="Used to calibrate the tone of drafted advice memos and letters."
            className={inputClass}
          />
        </div>

        <div className="flex items-center justify-between border-t border-border pt-4">
          <div className="text-xs text-muted-foreground">
            Plan: <span className="font-medium text-foreground">{settings.tier}</span> ·{" "}
            {settings.subscription_status}
          </div>
          <div className="flex items-center gap-3">
            {saved && <span className="text-xs text-green-700">Saved</span>}
            {error && <span className="text-xs text-destructive">{error}</span>}
            <button
              onClick={handleSave}
              disabled={saving}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition-all duration-200 hover:bg-accent disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save changes"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
