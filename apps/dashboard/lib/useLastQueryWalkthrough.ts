"use client";

import { useState } from "react";

interface QueryListItem {
  id: string;
  created_at: string;
}

interface VerificationIssue {
  claim: string;
  suggested_correction: string;
}

interface QueryDetail {
  question: string;
  citations: { citation: string; url: string; excerpt: string }[];
  verification_result: { overall_status: string; issues: VerificationIssue[] } | null;
  created_at: string;
}

export function relativeTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const dayDiff = Math.round(
    (new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() -
      new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()) /
      86400000
  );
  if (dayDiff <= 0) return "today";
  if (dayDiff === 1) return "yesterday";
  if (dayDiff < 7) return `${dayDiff} days ago`;
  return date.toLocaleDateString("en-AU");
}

// Fetches the persona's recent queries (with citations and verification
// results), on demand - shared by the identity strip and the onboarding tour
// so both show the exact same real data instead of duplicating the fetch.
export function useLastQueryWalkthrough() {
  const [loading, setLoading] = useState(false);
  const [lastQuery, setLastQuery] = useState<QueryDetail | null>(null);
  const [issueExample, setIssueExample] = useState<QueryDetail | null>(null);
  const [noQueries, setNoQueries] = useState(false);
  const [fetched, setFetched] = useState(false);

  async function load() {
    if (fetched) return;
    setFetched(true);
    setLoading(true);
    try {
      const listRes = await fetch("/api/query");
      const list: QueryListItem[] = listRes.ok ? await listRes.json() : [];
      if (list.length === 0) {
        setNoQueries(true);
        return;
      }
      // Fetch details for the last few queries so the safety-net example
      // below can find a real caught mistake even if the very last question
      // happened to come back clean.
      const details = await Promise.all(
        list.slice(0, 5).map((q) =>
          fetch(`/api/query/${q.id}`).then((r) => (r.ok ? (r.json() as Promise<QueryDetail>) : null))
        )
      );
      const loaded = details.filter((d): d is QueryDetail => d !== null);
      if (loaded.length > 0) setLastQuery(loaded[0]);
      setIssueExample(loaded.find((d) => (d.verification_result?.issues?.length ?? 0) > 0) ?? null);
    } catch {
      // Non-fatal - callers just show without the walkthrough section.
    } finally {
      setLoading(false);
    }
  }

  const firstIssue = issueExample?.verification_result?.issues?.[0];
  const distinctCitations = lastQuery
    ? Array.from(new Set(lastQuery.citations.map((c) => c.citation)))
    : [];

  return { load, loading, lastQuery, issueExample, noQueries, firstIssue, distinctCitations };
}
