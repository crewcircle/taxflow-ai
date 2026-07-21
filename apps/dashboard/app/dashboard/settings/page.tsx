"use client";

import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { createClient } from "@/lib/supabase/client";

interface StaffMember {
  name: string;
  role: string;
}

// Starting point, not a closed list - "Other" lets a firm type their own role.
// Mirrors DEFAULT_STAFF_ROLES in apps/backend/src/taxflow/routers/settings.py.
const DEFAULT_STAFF_ROLES = [
  "Principal/Director",
  "Senior Accountant",
  "Accountant",
  "Graduate/Associate",
  "Bookkeeper",
];

interface ClientSettings {
  business_name: string;
  email: string;
  phone: string | null;
  voice_sample: string | null;
  tier: string;
  subscription_status: string;
  staff_directory: StaffMember[] | null;
}

interface DocumentTemplate {
  template_key: string;
  label: string;
  body: string;
  is_custom: boolean;
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<ClientSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [newStaffName, setNewStaffName] = useState("");
  const [newStaffRole, setNewStaffRole] = useState(DEFAULT_STAFF_ROLES[0]);

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
          staff_directory: settings.staff_directory ?? [],
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

  function handleAddStaff() {
    if (!settings || !newStaffName.trim()) return;
    setSettings({
      ...settings,
      staff_directory: [...(settings.staff_directory ?? []), { name: newStaffName.trim(), role: newStaffRole }],
    });
    setNewStaffName("");
  }

  function handleRemoveStaff(index: number) {
    if (!settings) return;
    setSettings({
      ...settings,
      staff_directory: (settings.staff_directory ?? []).filter((_, i) => i !== index),
    });
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

          <div className="space-y-2">
            <Label>Staff</Label>
            <p className="text-xs text-muted-foreground">
              Names and roles for the &quot;reviewed and approved by&quot; sign-off on saved documents.
              This is a good-faith record, not a login — anyone on your account can select any name.
            </p>
            {(settings.staff_directory ?? []).length > 0 && (
              <ul className="space-y-1.5">
                {(settings.staff_directory ?? []).map((member, i) => (
                  <li
                    key={i}
                    className="flex items-center justify-between rounded-md border border-border px-3 py-1.5 text-sm"
                  >
                    <span>
                      {member.name} <span className="text-muted-foreground">· {member.role}</span>
                    </span>
                    <button
                      type="button"
                      onClick={() => handleRemoveStaff(i)}
                      className="text-muted-foreground hover:text-destructive"
                      aria-label={`Remove ${member.name}`}
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <Input
                value={newStaffName}
                onChange={(e) => setNewStaffName(e.target.value)}
                placeholder="Staff name"
                className="h-9 max-w-[180px]"
              />
              <Select value={newStaffRole} onValueChange={setNewStaffRole}>
                <SelectTrigger size="sm" className="w-[170px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DEFAULT_STAFF_ROLES.map((role) => (
                    <SelectItem key={role} value={role}>
                      {role}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button type="button" variant="outline" size="sm" onClick={handleAddStaff} disabled={!newStaffName.trim()}>
                Add
              </Button>
            </div>
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

      <DocumentTemplatesCard />

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

function DocumentTemplatesCard() {
  const [templates, setTemplates] = useState<DocumentTemplate[] | null>(null);
  const [selectedKey, setSelectedKey] = useState<string>("");
  const [body, setBody] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const r = await fetch("/api/settings/templates");
      if (!r.ok) throw new Error();
      const data: DocumentTemplate[] = await r.json();
      setTemplates(data);
      if (data.length > 0) {
        const current = data.find((t) => t.template_key === selectedKey) ?? data[0];
        setSelectedKey(current.template_key);
        setBody(current.body);
      }
    } catch {
      setError("Could not load document templates");
    }
  }

  useEffect(() => {
    // Kick off the async load. State updates happen inside the resolved
    // promise, not synchronously in the effect body.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selected = templates?.find((t) => t.template_key === selectedKey) ?? null;

  function handleSelect(key: string) {
    setSelectedKey(key);
    setSaved(false);
    setError(null);
    const t = templates?.find((x) => x.template_key === key);
    setBody(t?.body ?? "");
  }

  async function handleSave() {
    if (!selectedKey || !body.trim()) return;
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const r = await fetch(`/api/settings/templates/${encodeURIComponent(selectedKey)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body }),
      });
      if (!r.ok) throw new Error();
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      await load();
    } catch {
      setError("Could not save template - please try again");
    } finally {
      setSaving(false);
    }
  }

  async function handleReset() {
    if (!selectedKey) return;
    setResetting(true);
    setSaved(false);
    setError(null);
    try {
      const r = await fetch(`/api/settings/templates/${encodeURIComponent(selectedKey)}`, {
        method: "DELETE",
      });
      if (!r.ok) throw new Error();
      await load();
    } catch {
      setError("Could not reset template - please try again");
    } finally {
      setResetting(false);
    }
  }

  return (
    <Card>
      <CardContent className="space-y-4">
        <div>
          <h2 className="text-sm font-semibold">Document templates</h2>
          <p className="text-xs text-muted-foreground">
            Edit the drafting instructions used to generate advice memos and client letters for
            your firm - the two document types drafted from a saved answer. Other saved document
            types keep the answer as written. Reset any template to restore the built-in default.
            Australian English and required section checks always apply.
          </p>
        </div>

        {!templates ? (
          <p className="text-sm text-muted-foreground">{error ?? "Loading..."}</p>
        ) : (
          <>
            <div className="space-y-1.5">
              <Label htmlFor="template_key">Template</Label>
              <Select value={selectedKey} onValueChange={handleSelect}>
                <SelectTrigger id="template_key" className="w-full">
                  <SelectValue placeholder="Select a document type" />
                </SelectTrigger>
                <SelectContent>
                  {templates.map((t) => (
                    <SelectItem key={t.template_key} value={t.template_key}>
                      {t.label}
                      {t.is_custom ? " (customised)" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="template_body">Template body</Label>
              <Textarea
                id="template_body"
                rows={14}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                className="font-mono text-xs"
              />
            </div>

            <div className="flex items-center justify-between">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleReset}
                disabled={resetting || !selected?.is_custom}
              >
                {resetting ? "Resetting..." : "Reset to default"}
              </Button>
              <div className="flex items-center gap-3">
                {saved && <span className="text-xs text-green-700">Saved</span>}
                {error && <span className="text-xs text-destructive">{error}</span>}
                <Button onClick={handleSave} disabled={saving || !body.trim()}>
                  {saving ? "Saving..." : "Save template"}
                </Button>
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
