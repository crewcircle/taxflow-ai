"use client";

import { useEffect, useRef, useState } from "react";
import { User } from "lucide-react";
import { Input } from "@/components/ui/input";

// `id` is null when the name has real work on file (documents/queries) but
// hasn't been registered yet — see FirmClientsRepo.list_for_client's
// fallback. This component only ever writes the name into a free-text field,
// so an unregistered match is just as selectable as a registered one.
interface FirmClient {
  id: string | null;
  name: string;
  registered?: boolean;
}

interface ClientAutocompleteProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
}

// Free text is still allowed - a first-time client name isn't blocked - but
// past names are suggested so a typo doesn't silently fragment one client's
// history into two (the fix for the "Client (optional)" free-text field
// raised in the practice-principal audit).
export function ClientAutocomplete({ value, onChange, placeholder, className }: ClientAutocompleteProps) {
  const [suggestions, setSuggestions] = useState<FirmClient[]>([]);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handle = setTimeout(() => {
      const search = value.trim();
      fetch(`/api/firm-clients${search ? `?search=${encodeURIComponent(search)}` : ""}`)
        .then((r) => (r.ok ? r.json() : []))
        .then(setSuggestions)
        .catch(() => setSuggestions([]));
    }, 200);
    return () => clearTimeout(handle);
  }, [value]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div ref={containerRef} className="relative">
      <Input
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        placeholder={placeholder ?? "Client (optional)"}
        className={className}
        autoComplete="off"
      />
      {open && suggestions.length > 0 && (
        <ul className="absolute z-10 mt-1 w-full min-w-[180px] rounded-md border border-border bg-popover py-1 shadow-md">
          {suggestions.map((c) => (
            <li key={c.id ?? c.name}>
              <button
                type="button"
                className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-left text-sm hover:bg-accent/10"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  onChange(c.name);
                  setOpen(false);
                }}
              >
                <User className="size-3.5 text-muted-foreground" />
                <span className="flex-1">{c.name}</span>
                {c.registered === false && (
                  <span className="text-xs text-muted-foreground">not yet registered</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
