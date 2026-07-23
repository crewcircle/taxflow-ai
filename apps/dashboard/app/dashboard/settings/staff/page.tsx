"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { canManageStaff, type Role } from "@/lib/rbac";

interface StaffRow {
  id: string;
  email: string;
  role: Role;
  display_name: string | null;
  status: "invited" | "active" | "removed";
}

const ROLE_LABELS: Record<Role, string> = {
  owner: "Owner",
  reviewer: "Reviewer",
  staff: "Staff",
};

const ROLE_DESCRIPTIONS: Record<Role, string> = {
  owner: "Full access - billing, staff management, approve or delete anything.",
  reviewer: "Can approve documents and ATO responses, resolve flagged claims.",
  staff: "Everyday use - ask questions, draft documents. Can't approve or manage the team.",
};

export default function StaffPage() {
  const [myRole, setMyRole] = useState<Role | null>(null);
  const [roster, setRoster] = useState<StaffRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<Role>("staff");
  const [inviting, setInviting] = useState(false);
  const [inviteError, setInviteError] = useState<string | null>(null);

  function loadRoster() {
    fetch("/api/staff")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setRoster)
      .catch(() => setError("Could not load the team roster"));
  }

  useEffect(() => {
    fetch("/api/settings")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => setMyRole(d.client?.role ?? "owner"))
      .catch(() => setMyRole("owner"));
    loadRoster();
  }, []);

  async function handleInvite() {
    if (!inviteEmail.trim()) return;
    setInviting(true);
    setInviteError(null);
    try {
      const response = await fetch("/api/staff", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: inviteEmail.trim(), role: inviteRole }),
      });
      if (response.status === 409) {
        setInviteError("This email is already on the roster");
        return;
      }
      if (!response.ok) throw new Error();
      setInviteEmail("");
      setInviteRole("staff");
      loadRoster();
    } catch {
      setInviteError("Could not send the invite - please try again");
    } finally {
      setInviting(false);
    }
  }

  async function handleRoleChange(member: StaffRow, role: Role) {
    const response = await fetch(`/api/staff/${member.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    });
    if (!response.ok) {
      setError(
        response.status === 409
          ? "Can't demote the firm's last remaining Owner"
          : "Could not update this member's role"
      );
      return;
    }
    loadRoster();
  }

  async function handleRemove(member: StaffRow) {
    const response = await fetch(`/api/staff/${member.id}`, { method: "DELETE" });
    if (!response.ok) {
      setError(
        response.status === 409
          ? "Can't remove the firm's last remaining Owner"
          : "Could not remove this member"
      );
      return;
    }
    loadRoster();
  }

  const canManage = canManageStaff(myRole);

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <Link
          href="/dashboard/settings"
          className="mb-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-3" /> Settings
        </Link>
        <h1 className="text-xl font-semibold">Team</h1>
        <p className="text-sm text-muted-foreground">
          Who has a login to this firm&apos;s account, and what they can do. Owner can manage
          billing and the team; Reviewer can also approve documents; Staff can ask
          questions and draft documents.
        </p>
      </div>

      <Card>
        <CardContent className="space-y-3">
          {roster === null ? (
            <p className="text-sm text-muted-foreground">{error ?? "Loading..."}</p>
          ) : roster.length === 0 ? (
            <p className="text-sm text-muted-foreground">No team members yet.</p>
          ) : (
            <ul className="space-y-2">
              {roster.map((member) => (
                <li
                  key={member.id}
                  className="flex items-center justify-between rounded-md border border-border px-3 py-2"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">
                      {member.display_name || member.email}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">{member.email}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {member.status === "invited" && (
                      <Badge variant="outline" className="text-[10px]">
                        Invited
                      </Badge>
                    )}
                    {canManage ? (
                      <Select
                        value={member.role}
                        onValueChange={(role) => handleRoleChange(member, role as Role)}
                      >
                        <SelectTrigger size="sm" className="w-[110px]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {(Object.keys(ROLE_LABELS) as Role[]).map((role) => (
                            <SelectItem key={role} value={role}>
                              {ROLE_LABELS[role]}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <Badge variant="outline" className="text-[10px]">
                        {ROLE_LABELS[member.role]}
                      </Badge>
                    )}
                    {canManage && (
                      <button
                        type="button"
                        onClick={() => handleRemove(member)}
                        className="text-muted-foreground hover:text-destructive"
                        aria-label={`Remove ${member.display_name || member.email}`}
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
          {error && <p className="text-xs text-destructive">{error}</p>}
        </CardContent>
      </Card>

      {canManage && (
        <Card>
          <CardContent className="space-y-3">
            <div>
              <h2 className="text-sm font-semibold">Invite someone</h2>
              <p className="text-xs text-muted-foreground">{ROLE_DESCRIPTIONS[inviteRole]}</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Input
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                placeholder="name@firm.com.au"
                className="h-9 max-w-[220px]"
                type="email"
              />
              <Select value={inviteRole} onValueChange={(role) => setInviteRole(role as Role)}>
                <SelectTrigger size="sm" className="w-[130px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(ROLE_LABELS) as Role[]).map((role) => (
                    <SelectItem key={role} value={role}>
                      {ROLE_LABELS[role]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                type="button"
                onClick={handleInvite}
                disabled={inviting || !inviteEmail.trim()}
              >
                {inviting ? "Sending..." : "Send invite"}
              </Button>
            </div>
            {inviteError && <p className="text-xs text-destructive">{inviteError}</p>}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
