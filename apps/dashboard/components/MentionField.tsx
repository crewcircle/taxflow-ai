"use client";

import { useEffect, useState, type KeyboardEvent, type ReactNode } from "react";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

interface StaffMember {
  id: string;
  email: string;
  display_name: string | null;
  role: string;
  status: string;
}

// The roster rarely changes within a session, and every comment composer on
// the page (root composer, each thread's reply box, each edit box) would
// otherwise re-fetch it independently - one in-memory cache shared across all
// of them, refetched fresh on the next full page load.
let cachedRoster: StaffMember[] | null = null;
let rosterPromise: Promise<StaffMember[]> | null = null;

function fetchRoster(): Promise<StaffMember[]> {
  if (cachedRoster) return Promise.resolve(cachedRoster);
  rosterPromise ??= fetch("/api/staff")
    .then((r) => (r.ok ? r.json() : []))
    .then((data: StaffMember[]) => {
      cachedRoster = Array.isArray(data) ? data.filter((u) => u.status !== "removed") : [];
      return cachedRoster;
    })
    .catch(() => []);
  return rosterPromise;
}

function mentionLabel(u: StaffMember): string {
  return u.display_name?.trim() || u.email;
}

// @[Display Name](user-id) - parsed back out server-side (annotations.py's
// _MENTION_PATTERN) to resolve who actually gets notified; the display name
// half is cosmetic only, never trusted.
const MENTION_TOKEN_PATTERN = /@\[([^\]]*)\]\(([0-9a-fA-F-]{36})\)/g;

/** Render a comment body with @mention tokens shown as styled chips instead
 * of the raw markdown-ish token text. */
export function renderMentionBody(body: string): ReactNode[] {
  const parts: ReactNode[] = [];
  let lastIndex = 0;
  let key = 0;
  MENTION_TOKEN_PATTERN.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = MENTION_TOKEN_PATTERN.exec(body)) !== null) {
    if (match.index > lastIndex) parts.push(body.slice(lastIndex, match.index));
    parts.push(
      <span key={key++} className="rounded bg-accent/15 px-1 font-medium text-accent">
        @{match[1]}
      </span>
    );
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < body.length) parts.push(body.slice(lastIndex));
  return parts;
}

type FieldProps = {
  as?: "textarea" | "input";
  value: string;
  onChange: (value: string) => void;
  className?: string;
  placeholder?: string;
  rows?: number;
  autoFocus?: boolean;
  onKeyDown?: (e: KeyboardEvent<HTMLTextAreaElement | HTMLInputElement>) => void;
};

/** A Textarea/Input with an "@" trigger that autocompletes against the
 * firm's staff roster and inserts an @[Name](id) token - the same UI for
 * the new-comment composer, thread replies, and edits. */
export function MentionField({ as = "textarea", value, onChange, className, ...rest }: FieldProps) {
  const [roster, setRoster] = useState<StaffMember[]>([]);
  const [query, setQuery] = useState<string | null>(null);
  const [triggerIndex, setTriggerIndex] = useState<number | null>(null);

  useEffect(() => {
    void fetchRoster().then(setRoster);
  }, []);

  const matches =
    query == null
      ? []
      : roster.filter((u) => mentionLabel(u).toLowerCase().includes(query.toLowerCase())).slice(0, 6);

  function handleChange(e: React.ChangeEvent<HTMLTextAreaElement | HTMLInputElement>) {
    const next = e.target.value;
    onChange(next);

    const caret = e.target.selectionStart ?? next.length;
    const uptoCaret = next.slice(0, caret);
    const atIndex = uptoCaret.lastIndexOf("@");
    if (atIndex === -1 || /\s/.test(uptoCaret.slice(atIndex + 1))) {
      setQuery(null);
      setTriggerIndex(null);
      return;
    }
    setQuery(uptoCaret.slice(atIndex + 1));
    setTriggerIndex(atIndex);
  }

  function selectMention(u: StaffMember) {
    if (triggerIndex == null) return;
    const before = value.slice(0, triggerIndex);
    const after = value.slice(triggerIndex + 1 + (query?.length ?? 0));
    onChange(`${before}@[${mentionLabel(u)}](${u.id}) ${after}`);
    setQuery(null);
    setTriggerIndex(null);
  }

  return (
    <div className="relative flex-1">
      {as === "input" ? (
        <Input
          value={value}
          onChange={handleChange}
          className={className}
          placeholder={rest.placeholder}
          autoFocus={rest.autoFocus}
          onKeyDown={rest.onKeyDown}
        />
      ) : (
        <Textarea
          value={value}
          onChange={handleChange}
          className={className}
          placeholder={rest.placeholder}
          rows={rest.rows}
          autoFocus={rest.autoFocus}
          onKeyDown={rest.onKeyDown}
        />
      )}
      {query != null && matches.length > 0 && (
        <div className="absolute z-50 mt-1 w-56 overflow-hidden rounded-md border border-border bg-popover text-popover-foreground shadow-lg">
          {matches.map((u) => (
            <button
              key={u.id}
              type="button"
              // mousedown (not click) fires before the field blurs, so the
              // caret/selection state selectMention relies on is still there.
              onMouseDown={(e) => {
                e.preventDefault();
                selectMention(u);
              }}
              className={cn(
                "flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-left text-xs hover:bg-muted"
              )}
            >
              <span className="font-medium">{mentionLabel(u)}</span>
              <span className="text-[10px] uppercase text-muted-foreground">{u.role}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
