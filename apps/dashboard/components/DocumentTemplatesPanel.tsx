"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export interface DocumentTemplate {
  template_key: string;
  label: string;
  body: string;
  is_custom: boolean;
}

// Drafting-instruction editor for a firm's document templates (advice memos,
// client letters, etc). Lives inline in the "Save as document" workflow
// (AnswerActionsBar) rather than buried in general Settings - templates are a
// property of the document TYPE you're about to generate, not a firm-wide
// preference you'd go looking for separately.
export function DocumentTemplatesPanel({ initialKey }: { initialKey?: string }) {
  const [templates, setTemplates] = useState<DocumentTemplate[] | null>(null);
  const [selectedKey, setSelectedKey] = useState<string>(initialKey ?? "");
  const [body, setBody] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load(preferredKey?: string) {
    try {
      const r = await fetch("/api/settings/templates");
      if (!r.ok) throw new Error();
      const data: DocumentTemplate[] = await r.json();
      setTemplates(data);
      if (data.length > 0) {
        const current = data.find((t) => t.template_key === (preferredKey ?? selectedKey)) ?? data[0];
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
    void load(initialKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialKey]);

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
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        Edit the drafting instructions used to generate advice memos and client letters for your
        firm - the two document types drafted from a saved answer. Other saved document types keep
        the answer as written. Reset any template to restore the built-in default. Australian
        English and required section checks always apply.
      </p>

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
    </div>
  );
}
