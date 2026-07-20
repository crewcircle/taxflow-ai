"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowRight, Briefcase, Check, Plus, Search, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

interface FirmClient {
  id: string;
  name: string;
}

export interface Engagement {
  id: string;
  firm_client_id: string;
  engagement_number: number;
  description: string;
  status: string;
}

// The chosen engagement, plus the end-client name so callers can keep sending
// the legacy `client_ref` string alongside `engagement_id` (query/document/ATO
// rows carry both for back-compat and highlighting).
export interface EngagementSelection {
  engagement: Engagement;
  clientName: string;
}

interface EngagementPickerProps {
  value: EngagementSelection | null;
  onChange: (selection: EngagementSelection | null) => void;
  // Rendered as the trigger label when nothing is selected yet.
  triggerLabel?: string;
  className?: string;
  disabled?: boolean;
}

// sessionStorage keys so a repeat job in the same tab is one click: we remember
// the last-used client and engagement and offer them as a fast-path.
const LAST_CLIENT_KEY = "taxflow.lastEngagementClient";
const LAST_ENGAGEMENT_KEY = "taxflow.lastEngagement";

function readRemembered<T>(key: string): T | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function defaultDescription(): string {
  return `General tax research — ${new Date().toISOString().slice(0, 10)}`;
}

// A required, low-friction engagement picker shown before a job starts. Step 1
// picks or creates the real end-client (capturing firm_clients.id, unlike the
// bare ClientAutocomplete which only ever passed a name string). Step 2 picks
// an existing open engagement for that client or creates a new one (with an
// optional description that falls back to a dated default). The chosen
// engagement is threaded into the query stream / document generate / ATO upload
// so every unit of work is attributed to a first-class engagement.
export function EngagementPicker({
  value,
  onChange,
  triggerLabel = "Choose client & engagement",
  className,
  disabled,
}: EngagementPickerProps) {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<"client" | "engagement">("client");

  // Step 1 state
  const [clientQuery, setClientQuery] = useState("");
  const [suggestions, setSuggestions] = useState<FirmClient[]>([]);
  const [selectedClient, setSelectedClient] = useState<FirmClient | null>(null);
  const [creatingClient, setCreatingClient] = useState(false);

  // Step 2 state
  const [engagements, setEngagements] = useState<Engagement[]>([]);
  const [loadingEngagements, setLoadingEngagements] = useState(false);
  const [chosenEngagementId, setChosenEngagementId] = useState<string | null>(null);
  const [description, setDescription] = useState("");
  const [creatingEngagement, setCreatingEngagement] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const remembered = readRemembered<EngagementSelection>(LAST_ENGAGEMENT_KEY);

  // Client suggestions, debounced against the register.
  useEffect(() => {
    if (!open || step !== "client") return;
    const handle = setTimeout(() => {
      const search = clientQuery.trim();
      fetch(`/api/firm-clients${search ? `?search=${encodeURIComponent(search)}` : ""}`)
        .then((r) => (r.ok ? r.json() : []))
        .then((rows: FirmClient[]) => setSuggestions(Array.isArray(rows) ? rows : []))
        .catch(() => setSuggestions([]));
    }, 200);
    return () => clearTimeout(handle);
  }, [clientQuery, open, step]);

  const loadEngagements = useCallback((firmClientId: string) => {
    setLoadingEngagements(true);
    fetch(`/api/engagements?firm_client_id=${encodeURIComponent(firmClientId)}`)
      .then((r) => (r.ok ? r.json() : []))
      .then((rows: Engagement[]) => setEngagements(Array.isArray(rows) ? rows : []))
      .catch(() => setEngagements([]))
      .finally(() => setLoadingEngagements(false));
  }, []);

  function resetFlow() {
    setStep("client");
    setClientQuery("");
    setSuggestions([]);
    setSelectedClient(null);
    setEngagements([]);
    setChosenEngagementId(null);
    setDescription("");
    setError(null);
  }

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (next) {
      resetFlow();
      const lastClient = readRemembered<FirmClient>(LAST_CLIENT_KEY);
      if (lastClient) setClientQuery(lastClient.name);
    }
  }

  // Resolve the chosen client to a real firm_clients.id: an exact
  // (case-insensitive) name match reuses the existing row, otherwise POST
  // creates it. The backend get-or-create is idempotent, so a name that already
  // exists still returns its id.
  async function selectClient(client: FirmClient) {
    setSelectedClient(client);
    try {
      window.sessionStorage.setItem(LAST_CLIENT_KEY, JSON.stringify(client));
    } catch {
      // Non-fatal: remembering is a convenience only.
    }
    setStep("engagement");
    loadEngagements(client.id);
  }

  async function handleClientContinue() {
    setError(null);
    const typed = clientQuery.trim();
    if (!typed) return;
    const exact = suggestions.find((c) => c.name.toLowerCase() === typed.toLowerCase());
    if (exact) {
      await selectClient(exact);
      return;
    }
    setCreatingClient(true);
    try {
      const response = await fetch("/api/firm-clients", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: typed }),
      });
      if (!response.ok) throw new Error("Failed");
      const created: FirmClient = await response.json();
      await selectClient(created);
    } catch {
      setError("Could not create that client — please try again");
    } finally {
      setCreatingClient(false);
    }
  }

  function commitSelection(engagement: Engagement, client: FirmClient) {
    const selection: EngagementSelection = { engagement, clientName: client.name };
    try {
      window.sessionStorage.setItem(LAST_ENGAGEMENT_KEY, JSON.stringify(selection));
    } catch {
      // Non-fatal.
    }
    onChange(selection);
    setOpen(false);
  }

  async function handleEngagementConfirm() {
    if (!selectedClient) return;
    setError(null);
    // Existing engagement chosen.
    if (chosenEngagementId) {
      const existing = engagements.find((e) => e.id === chosenEngagementId);
      if (existing) {
        commitSelection(existing, selectedClient);
        return;
      }
    }
    // Otherwise create a new engagement (description optional → dated default).
    setCreatingEngagement(true);
    try {
      const response = await fetch("/api/engagements", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          firm_client_id: selectedClient.id,
          description: description.trim() || undefined,
        }),
      });
      if (!response.ok) throw new Error("Failed");
      const created: Engagement = await response.json();
      commitSelection(created, selectedClient);
    } catch {
      setError("Could not create the engagement — please try again");
    } finally {
      setCreatingEngagement(false);
    }
  }

  const typed = clientQuery.trim();
  const hasExactMatch = suggestions.some((c) => c.name.toLowerCase() === typed.toLowerCase());
  const showCreateRow = typed.length > 0 && !hasExactMatch;
  // "New engagement" is the implicit choice whenever no existing one is picked.
  const isCreatingNewEngagement = chosenEngagementId === null;

  return (
    <>
      <Button
        type="button"
        variant={value ? "secondary" : "outline"}
        size="sm"
        className={cn("gap-1.5", className)}
        onClick={() => handleOpenChange(true)}
        disabled={disabled}
      >
        <Briefcase className="size-3.5" />
        {value
          ? `#${value.engagement.engagement_number} · ${value.clientName}`
          : triggerLabel}
      </Button>

      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent className="sm:max-w-md">
          {step === "client" ? (
            <>
              <DialogHeader>
                <DialogTitle>Who is this for?</DialogTitle>
                <DialogDescription>
                  Every new job is attributed to a client.
                </DialogDescription>
              </DialogHeader>

              {remembered && (
                <button
                  type="button"
                  className="flex w-full items-center gap-2.5 rounded-lg border border-accent/40 bg-accent/10 px-3 py-2 text-left"
                  onClick={() =>
                    selectClient({
                      id: remembered.engagement.firm_client_id,
                      name: remembered.clientName,
                    })
                  }
                >
                  <User className="size-4 text-accent" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium">{remembered.clientName}</span>
                    <span className="block text-xs text-muted-foreground">
                      Last used · #{remembered.engagement.engagement_number}
                    </span>
                  </span>
                  <Badge variant="secondary">Continue</Badge>
                </button>
              )}

              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  autoFocus
                  value={clientQuery}
                  onChange={(e) => setClientQuery(e.target.value)}
                  placeholder="Search clients or type a new name…"
                  className="pl-8"
                  autoComplete="off"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && typed) {
                      e.preventDefault();
                      handleClientContinue();
                    }
                  }}
                />
              </div>

              <ul className="max-h-48 divide-y divide-border overflow-y-auto rounded-lg border border-border">
                {suggestions.map((c) => (
                  <li key={c.id}>
                    <button
                      type="button"
                      className="flex w-full items-center gap-2.5 px-3 py-2 text-left hover:bg-muted"
                      onClick={() => selectClient(c)}
                    >
                      <User className="size-4 text-muted-foreground" />
                      <span className="flex-1 text-sm font-medium">{c.name}</span>
                    </button>
                  </li>
                ))}
                {showCreateRow && (
                  <li>
                    <button
                      type="button"
                      className="flex w-full items-center gap-2.5 px-3 py-2 text-left hover:bg-muted"
                      onClick={handleClientContinue}
                      disabled={creatingClient}
                    >
                      <Plus className="size-4 text-accent" />
                      <span className="flex-1 text-sm font-medium text-accent">
                        {creatingClient ? "Creating…" : `Create new client “${typed}”`}
                      </span>
                    </button>
                  </li>
                )}
                {suggestions.length === 0 && !showCreateRow && (
                  <li className="px-3 py-2 text-sm text-muted-foreground">
                    Start typing to search or add a client.
                  </li>
                )}
              </ul>

              {error && <p className="text-sm text-destructive">{error}</p>}

              <DialogFooter>
                <Button
                  type="button"
                  size="sm"
                  onClick={handleClientContinue}
                  disabled={!typed || creatingClient}
                >
                  Continue
                  <ArrowRight className="size-3.5" />
                </Button>
              </DialogFooter>
            </>
          ) : (
            <>
              <DialogHeader>
                <DialogTitle>Which engagement?</DialogTitle>
                <DialogDescription>
                  Group this job under an existing open engagement, or start a new one
                  {selectedClient ? ` for ${selectedClient.name}` : ""}.
                </DialogDescription>
              </DialogHeader>

              <ul className="max-h-48 divide-y divide-border overflow-y-auto rounded-lg border border-border">
                {loadingEngagements && (
                  <li className="px-3 py-2 text-sm text-muted-foreground">Loading…</li>
                )}
                {!loadingEngagements &&
                  engagements.map((e) => (
                    <li key={e.id}>
                      <button
                        type="button"
                        className={cn(
                          "flex w-full items-center gap-2.5 px-3 py-2 text-left hover:bg-muted",
                          chosenEngagementId === e.id && "bg-accent/10"
                        )}
                        onClick={() => setChosenEngagementId(e.id)}
                      >
                        <Briefcase className="size-4 text-muted-foreground" />
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-2 text-sm font-medium">
                            #{e.engagement_number} · {e.description}
                            <Badge
                              variant={e.status === "active" ? "secondary" : "outline"}
                              className="capitalize"
                            >
                              {e.status}
                            </Badge>
                          </span>
                        </span>
                        {chosenEngagementId === e.id && <Check className="size-4 text-accent" />}
                      </button>
                    </li>
                  ))}
                <li>
                  <button
                    type="button"
                    className={cn(
                      "flex w-full items-center gap-2.5 px-3 py-2 text-left hover:bg-muted",
                      isCreatingNewEngagement && "bg-accent/10"
                    )}
                    onClick={() => setChosenEngagementId(null)}
                  >
                    <Plus className="size-4 text-accent" />
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium text-accent">New engagement</span>
                      <span className="block text-xs text-muted-foreground">
                        Auto-numbered for this client
                      </span>
                    </span>
                    {isCreatingNewEngagement && <Check className="size-4 text-accent" />}
                  </button>
                </li>
              </ul>

              {isCreatingNewEngagement && (
                <div className="space-y-1.5">
                  <Label htmlFor="engagement-description">
                    Description{" "}
                    <span className="font-normal text-muted-foreground">(optional)</span>
                  </Label>
                  <Textarea
                    id="engagement-description"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    rows={2}
                    placeholder={defaultDescription()}
                  />
                  <p className="text-xs text-muted-foreground">
                    Leave blank to use the default: <b>{defaultDescription()}</b>
                  </p>
                </div>
              )}

              {error && <p className="text-sm text-destructive">{error}</p>}

              <DialogFooter className="sm:justify-between">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setStep("client")}
                >
                  Back
                </Button>
                <Button
                  type="button"
                  size="sm"
                  onClick={handleEngagementConfirm}
                  disabled={creatingEngagement}
                >
                  {creatingEngagement ? "Starting…" : "Start work"}
                  <ArrowRight className="size-3.5" />
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
