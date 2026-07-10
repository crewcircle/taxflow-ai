"use client";

import { useEffect, useState } from "react";
import { ExternalLink } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

interface AlertRow {
  id: string;
  source: string;
  alert_type: string;
  title: string;
  summary: string | null;
  url: string | null;
  detected_at: string;
}

export default function RegulatoryPage() {
  const [alerts, setAlerts] = useState<AlertRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/regulatory-alerts")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setAlerts)
      .catch(() => setError("Could not load regulatory updates"));
  }, []);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Regulatory Updates</h1>
        <p className="text-sm text-muted-foreground">
          New rulings and decisions detected from public AU regulator feeds, checked every 2 hours.
        </p>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {!alerts && !error && <p className="text-sm text-muted-foreground">Loading...</p>}
      {alerts && alerts.length === 0 && (
        <p className="text-sm text-muted-foreground">No regulatory updates detected yet.</p>
      )}

      {alerts && alerts.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Title</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Detected</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {alerts.map((alert) => (
                <TableRow key={alert.id}>
                  <TableCell className="font-medium">
                    {alert.url ? (
                      <a
                        href={alert.url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-accent hover:underline"
                      >
                        {alert.title}
                        <ExternalLink className="size-3" />
                      </a>
                    ) : (
                      alert.title
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground uppercase">{alert.source}</TableCell>
                  <TableCell>
                    <Badge variant="outline">{alert.alert_type.replace(/_/g, " ")}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {new Date(alert.detected_at).toLocaleDateString("en-AU")}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
