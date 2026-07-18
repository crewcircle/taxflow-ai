"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { ExternalLink, Network } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

// react-force-graph-2d renders to a <canvas> via the DOM and has no SSR
// support - load it client-side only, same reason every force-graph example
// in their own docs uses next/dynamic with ssr: false.
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

interface DocumentNode {
  id: string;
  type: "document";
  title: string;
  source_type: string;
  jurisdiction: string | null;
  source_url: string;
  chunk_count: number;
  is_current: boolean;
  last_scraped_at: string | null;
  topics: string[];
}

interface TopicNode {
  id: string;
  type: "topic";
  document_count: number;
}

type GraphNode = (DocumentNode | TopicNode) & { x?: number; y?: number };

interface GraphEdge {
  source: string;
  target: string;
}

interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

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
const TOPIC_COLOR = "#1d3557";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-AU", { year: "numeric", month: "short" });
}

export default function KnowledgeBasePage() {
  const [data, setData] = useState<GraphData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [topicFilter, setTopicFilter] = useState<string>("all");
  const [jurisdictionFilter, setJurisdictionFilter] = useState<string>("all");
  const [selected, setSelected] = useState<DocumentNode | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  useEffect(() => {
    fetch("/api/knowledge/graph")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("failed"))))
      .then(setData)
      .catch(() => setError("Could not load the knowledge base graph - please try again"));
  }, []);

  useEffect(() => {
    function measure() {
      if (containerRef.current) {
        setDimensions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        });
      }
    }
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  const documentNodes = useMemo(
    () => (data?.nodes.filter((n) => n.type === "document") as DocumentNode[]) ?? [],
    [data]
  );

  const jurisdictions = useMemo(
    () => Array.from(new Set(documentNodes.map((n) => n.jurisdiction).filter(Boolean))).sort() as string[],
    [documentNodes]
  );
  const topics = useMemo(
    () => Array.from(new Set(data?.nodes.filter((n) => n.type === "topic").map((n) => n.id) ?? [])).sort(),
    [data]
  );

  const filtered = useMemo<GraphData | null>(() => {
    if (!data) return null;
    if (topicFilter === "all" && jurisdictionFilter === "all") return data;

    const keptDocs = new Set(
      documentNodes
        .filter((n) => (topicFilter === "all" || n.topics.includes(topicFilter)) && (jurisdictionFilter === "all" || n.jurisdiction === jurisdictionFilter))
        .map((n) => n.id)
    );
    const edges = data.edges.filter((e) => keptDocs.has(e.source));
    const keptTopics = new Set(edges.map((e) => e.target));
    const nodes = data.nodes.filter((n) => (n.type === "document" ? keptDocs.has(n.id) : keptTopics.has(n.id)));
    return { nodes, edges };
  }, [data, documentNodes, topicFilter, jurisdictionFilter]);

  return (
    <div className="flex h-[calc(100vh-8rem)] min-h-[420px] w-full min-w-0 overflow-hidden rounded-xl border border-border">
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <Network className="size-4 text-muted-foreground" />
            <span className="text-sm font-semibold text-foreground">
              TaxFlow Knowledge Base
              {data && (
                <span className="ml-2 font-normal text-muted-foreground">
                  {documentNodes.length} sources across {topics.length} topics
                </span>
              )}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Select value={topicFilter} onValueChange={setTopicFilter}>
              <SelectTrigger size="sm" className="w-[190px]">
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
              <SelectTrigger size="sm" className="w-[160px]">
                <SelectValue placeholder="All jurisdictions" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All jurisdictions</SelectItem>
                <SelectItem value="federal">Federal</SelectItem>
                {jurisdictions.map((j) => (
                  <SelectItem key={j} value={j}>
                    {j}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div ref={containerRef} className="relative flex-1 overflow-hidden">
          {error && <p className="p-4 text-sm text-destructive">{error}</p>}
          {!error && !data && <p className="p-4 text-sm text-muted-foreground">Loading the knowledge base...</p>}
          {filtered && (
            <ForceGraph2D
              graphData={{ nodes: filtered.nodes, links: filtered.edges }}
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
                return node.type === "topic" ? TOPIC_COLOR : SOURCE_TYPE_COLORS[node.source_type] ?? "#94a3b8";
              }}
              linkColor={() => "#d4d4d8"}
              onNodeClick={(n: object) => {
                const node = n as GraphNode;
                if (node.type === "document") setSelected(node);
              }}
              cooldownTicks={100}
            />
          )}
        </div>
      </div>

      <div className="w-72 shrink-0 overflow-y-auto border-l border-border p-3">
        {!selected ? (
          <p className="p-2 text-xs text-muted-foreground">
            Click a node to see its details. Larger nodes are topics; smaller, coloured nodes are individual
            sources - colour follows source type.
          </p>
        ) : (
          <Card>
            <CardContent className="space-y-2 p-3 text-sm">
              <p className="font-medium text-foreground">{selected.title}</p>
              <div className="flex flex-wrap gap-1.5">
                <Badge variant="outline">{selected.source_type}</Badge>
                {selected.jurisdiction && <Badge variant="outline">{selected.jurisdiction}</Badge>}
                {!selected.is_current && (
                  <Badge variant="outline" className="border-amber-600/30 bg-amber-50 text-amber-800">
                    superseded
                  </Badge>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                {selected.chunk_count} indexed chunk{selected.chunk_count === 1 ? "" : "s"}
                {selected.last_scraped_at && ` · Refreshed ${formatDate(selected.last_scraped_at)}`}
              </p>
              {selected.topics.length > 0 && (
                <p className="text-xs text-muted-foreground">Topics: {selected.topics.join(", ")}</p>
              )}
              {selected.source_url && (
                <a
                  href={selected.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
                >
                  View source
                  <ExternalLink className="size-3" />
                </a>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
