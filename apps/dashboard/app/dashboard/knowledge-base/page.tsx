"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { ArrowDown, ArrowUp, ArrowUpDown, ExternalLink, LayoutGrid, Network } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

// react-force-graph-2d renders to a <canvas> via the DOM and has no SSR
// support - load it client-side only, same reason every force-graph example
// in their own docs uses next/dynamic with ssr: false.
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

interface Document {
  id: string;
  type: "document";
  title: string;
  source_type: string;
  jurisdiction: string;
  source_url: string;
  chunk_count: number;
  is_current: boolean;
  last_scraped_at: string | null;
  topics: string[];
  cited_count: number;
}

interface TopicNode {
  id: string;
  type: "topic";
  document_count: number;
}

type GraphNode = (Document | TopicNode) & { x?: number; y?: number };
type GroupBy = "topics" | "jurisdiction" | "source_type" | "status";

// One colour per source_type so the same palette is legible whether you're
// filtering by jurisdiction or browsing everything at once.
const SOURCE_TYPE_COLORS: Record<string, string> = {
  ato_ruling: "#f97316",
  ato_determination: "#fb923c",
  ato_pbr: "#fdba74",
  ato_guide: "#eab308",
  ato_news: "#a3a3a3",
  court_decision: "#8b5cf6",
  legislation: "#0ea5e9",
  state_ruling: "#22c55e",
};
const HUB_COLOR = "#1d3557";

// The nightly ingest cron (apps/backend/src/taxflow/scheduler.py, job
// "kb_ingestion") runs daily at 16:00 UTC = 2am Sydney - static because it's
// a fixed cron schedule, not something the API needs to round-trip.
const NEXT_INGEST_NOTE = "Sources are re-checked automatically every day at 2am Sydney time.";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-AU", { year: "numeric", month: "short", day: "numeric" });
}

function daysSince(iso: string): number {
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
}

function groupKeyOf(doc: Document, groupBy: GroupBy): string[] {
  switch (groupBy) {
    case "topics":
      return doc.topics;
    case "jurisdiction":
      return [doc.jurisdiction];
    case "source_type":
      return [doc.source_type];
    case "status":
      return [doc.is_current ? "Current" : "Superseded"];
  }
}

type SortKey = "title" | "source_type" | "jurisdiction" | "chunk_count" | "cited_count" | "last_scraped_at" | "is_current";

function SortHeader({
  label,
  sortKey,
  active,
  direction,
  onSort,
}: {
  label: string;
  sortKey: SortKey;
  active: SortKey;
  direction: "asc" | "desc";
  onSort: (key: SortKey) => void;
}) {
  const Icon = active !== sortKey ? ArrowUpDown : direction === "asc" ? ArrowUp : ArrowDown;
  return (
    <TableHead>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={cn(
          "inline-flex items-center gap-1 hover:text-foreground",
          active === sortKey ? "text-foreground" : "text-muted-foreground"
        )}
      >
        {label}
        <Icon className="size-3" />
      </button>
    </TableHead>
  );
}

export default function KnowledgeBasePage() {
  const [documents, setDocuments] = useState<Document[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"table" | "graph">("table");
  const [groupBy, setGroupBy] = useState<GroupBy>("topics");
  const [topicFilter, setTopicFilter] = useState<string>("all");
  const [jurisdictionFilter, setJurisdictionFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("last_scraped_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  useEffect(() => {
    fetch("/api/knowledge/graph")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("failed"))))
      .then((data) => setDocuments(data.documents))
      .catch(() => setError("Could not load the knowledge base - please try again"));
  }, []);

  useEffect(() => {
    function measure() {
      if (containerRef.current) {
        setDimensions({ width: containerRef.current.clientWidth, height: containerRef.current.clientHeight });
      }
    }
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  const topics = useMemo(
    () => Array.from(new Set(documents?.flatMap((d) => d.topics) ?? [])).sort(),
    [documents]
  );
  const jurisdictions = useMemo(
    () => Array.from(new Set(documents?.map((d) => d.jurisdiction) ?? [])).sort(),
    [documents]
  );

  const filtered = useMemo(() => {
    if (!documents) return [];
    return documents.filter((d) => {
      if (topicFilter !== "all" && !d.topics.includes(topicFilter)) return false;
      if (jurisdictionFilter !== "all" && d.jurisdiction !== jurisdictionFilter) return false;
      if (statusFilter === "current" && !d.is_current) return false;
      if (statusFilter === "superseded" && d.is_current) return false;
      if (search.trim() && !d.title.toLowerCase().includes(search.toLowerCase()) && !d.id.toLowerCase().includes(search.toLowerCase())) {
        return false;
      }
      return true;
    });
  }, [documents, topicFilter, jurisdictionFilter, statusFilter, search]);

  const sorted = useMemo(() => {
    const withDir = (cmp: number) => (sortDir === "asc" ? cmp : -cmp);
    return [...filtered].sort((a, b) => {
      switch (sortKey) {
        case "title":
          return withDir(a.title.localeCompare(b.title));
        case "source_type":
          return withDir(a.source_type.localeCompare(b.source_type));
        case "jurisdiction":
          return withDir(a.jurisdiction.localeCompare(b.jurisdiction));
        case "chunk_count":
          return withDir(a.chunk_count - b.chunk_count);
        case "cited_count":
          return withDir(a.cited_count - b.cited_count);
        case "is_current":
          return withDir(Number(a.is_current) - Number(b.is_current));
        case "last_scraped_at":
          return withDir((a.last_scraped_at ?? "").localeCompare(b.last_scraped_at ?? ""));
      }
    });
  }, [filtered, sortKey, sortDir]);

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  const staleCount = filtered.filter((d) => d.last_scraped_at && daysSince(d.last_scraped_at) > 30).length;
  const supersededCount = filtered.filter((d) => !d.is_current).length;
  const oldestRefresh = filtered.reduce<string | null>((oldest, d) => {
    if (!d.last_scraped_at) return oldest;
    return !oldest || d.last_scraped_at < oldest ? d.last_scraped_at : oldest;
  }, null);

  const graphData = useMemo(() => {
    const hubCounts = new Map<string, number>();
    const edges: { source: string; target: string }[] = [];
    for (const doc of filtered) {
      for (const key of groupKeyOf(doc, groupBy)) {
        hubCounts.set(key, (hubCounts.get(key) ?? 0) + 1);
        edges.push({ source: doc.id, target: key });
      }
    }
    const hubs: GraphNode[] = Array.from(hubCounts.entries()).map(([id, document_count]) => ({
      id,
      type: "topic",
      document_count,
    }));
    return { nodes: [...filtered, ...hubs] as GraphNode[], links: edges };
  }, [filtered, groupBy]);

  return (
    <div className="flex h-[calc(100vh-8rem)] min-h-[420px] w-full min-w-0 flex-col overflow-hidden rounded-xl border border-border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <Network className="size-4 text-muted-foreground" />
          <span className="text-sm font-semibold text-foreground">
            TaxFlow Knowledge Base
            {documents && (
              <span className="ml-2 font-normal text-muted-foreground">
                {documents.length} sources
                {supersededCount > 0 && ` · ${supersededCount} superseded`}
                {staleCount > 0 && ` · ${staleCount} not refreshed in 30+ days`}
              </span>
            )}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setView((v) => (v === "table" ? "graph" : "table"))}
            className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-foreground hover:bg-muted"
          >
            {view === "table" ? <Network className="size-3.5" /> : <LayoutGrid className="size-3.5" />}
            {view === "table" ? "Graph view" : "Table view"}
          </button>
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search citation or title..."
            className="h-8 w-[190px] text-xs"
          />
          <Select value={topicFilter} onValueChange={setTopicFilter}>
            <SelectTrigger size="sm" className="w-[170px]">
              <SelectValue placeholder="All topics" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All topics</SelectItem>
              {topics.map((t) => (
                <SelectItem key={t} value={t}>
                  {t}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={jurisdictionFilter} onValueChange={setJurisdictionFilter}>
            <SelectTrigger size="sm" className="w-[150px]">
              <SelectValue placeholder="All jurisdictions" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All jurisdictions</SelectItem>
              {jurisdictions.map((j) => (
                <SelectItem key={j} value={j}>
                  {j}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger size="sm" className="w-[140px]">
              <SelectValue placeholder="All statuses" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="current">Current only</SelectItem>
              <SelectItem value="superseded">Superseded only</SelectItem>
            </SelectContent>
          </Select>
          {view === "graph" && (
            <Select value={groupBy} onValueChange={(v) => setGroupBy(v as GroupBy)}>
              <SelectTrigger size="sm" className="w-[140px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="topics">Group by topic</SelectItem>
                <SelectItem value="jurisdiction">Group by jurisdiction</SelectItem>
                <SelectItem value="source_type">Group by source type</SelectItem>
                <SelectItem value="status">Group by status</SelectItem>
              </SelectContent>
            </Select>
          )}
        </div>
      </div>

      <div className="flex items-center justify-between gap-2 border-b border-border bg-muted/30 px-4 py-1.5 text-[11px] text-muted-foreground">
        <span>{NEXT_INGEST_NOTE}</span>
        {oldestRefresh && <span>Oldest source last refreshed {formatDate(oldestRefresh)}</span>}
      </div>

      {error && <p className="p-4 text-sm text-destructive">{error}</p>}
      {!error && !documents && <p className="p-4 text-sm text-muted-foreground">Loading the knowledge base...</p>}

      {documents && view === "table" && (
        <div className="flex-1 overflow-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <SortHeader label="Document" sortKey="title" active={sortKey} direction={sortDir} onSort={handleSort} />
                <SortHeader label="Type" sortKey="source_type" active={sortKey} direction={sortDir} onSort={handleSort} />
                <SortHeader label="Jurisdiction" sortKey="jurisdiction" active={sortKey} direction={sortDir} onSort={handleSort} />
                <TableHead>Topics</TableHead>
                <SortHeader label="Chunks" sortKey="chunk_count" active={sortKey} direction={sortDir} onSort={handleSort} />
                <SortHeader label="Cited" sortKey="cited_count" active={sortKey} direction={sortDir} onSort={handleSort} />
                <SortHeader label="Status" sortKey="is_current" active={sortKey} direction={sortDir} onSort={handleSort} />
                <SortHeader
                  label="Refreshed"
                  sortKey="last_scraped_at"
                  active={sortKey}
                  direction={sortDir}
                  onSort={handleSort}
                />
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((doc) => {
                const stale = doc.last_scraped_at ? daysSince(doc.last_scraped_at) > 30 : false;
                return (
                  <TableRow key={doc.id}>
                    <TableCell className="max-w-[260px]">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate font-medium text-foreground" title={doc.title}>
                          {doc.title}
                        </span>
                        {doc.source_url && (
                          <a href={doc.source_url} target="_blank" rel="noreferrer" className="shrink-0 text-accent">
                            <ExternalLink className="size-3" />
                          </a>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="outline"
                        style={{ borderColor: SOURCE_TYPE_COLORS[doc.source_type], color: SOURCE_TYPE_COLORS[doc.source_type] }}
                      >
                        {doc.source_type}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{doc.jurisdiction}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{doc.topics.join(", ") || "—"}</TableCell>
                    <TableCell className="text-xs tabular-nums text-muted-foreground">{doc.chunk_count}</TableCell>
                    <TableCell className="text-xs tabular-nums text-muted-foreground">
                      {doc.cited_count > 0 ? (
                        <span className="font-medium text-accent">{doc.cited_count}×</span>
                      ) : (
                        <span className="text-muted-foreground/60">not yet</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {doc.is_current ? (
                        <Badge variant="outline" className="border-green-600/30 text-green-700">
                          Current
                        </Badge>
                      ) : (
                        <Badge variant="outline" className="border-amber-600/30 bg-amber-50 text-amber-800">
                          Superseded
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className={cn("text-xs", stale ? "text-amber-700" : "text-muted-foreground")}>
                      {doc.last_scraped_at ? formatDate(doc.last_scraped_at) : "—"}
                      {stale && " (stale)"}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          {sorted.length === 0 && (
            <p className="p-4 text-sm text-muted-foreground">No sources match the current filters.</p>
          )}
        </div>
      )}

      {documents && view === "graph" && (
        <div ref={containerRef} className="relative flex-1 overflow-hidden">
          <ForceGraph2D
            graphData={graphData}
            width={dimensions.width}
            height={dimensions.height}
            nodeId="id"
            nodeLabel={(n: object) => {
              const node = n as GraphNode;
              return node.type === "topic" ? `${node.id} (${node.document_count})` : node.title;
            }}
            nodeVal={(n: object) => ((n as GraphNode).type === "topic" ? 8 : 3)}
            nodeColor={(n: object) => {
              const node = n as GraphNode;
              return node.type === "topic" ? HUB_COLOR : SOURCE_TYPE_COLORS[node.source_type] ?? "#94a3b8";
            }}
            linkColor={() => "#d4d4d8"}
            cooldownTicks={100}
          />
        </div>
      )}
    </div>
  );
}
