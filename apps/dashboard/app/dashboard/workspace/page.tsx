"use client";

import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { WorkspaceClientsTable } from "@/components/WorkspaceClientsTable";
import { DocumentTemplatesPanel } from "@/components/DocumentTemplatesPanel";
import DocumentsPage from "@/app/dashboard/documents/page";

// Three tabs, not four: Clients (the browsable client -> engagement ->
// conversation/document rollup - clicking an engagement or conversation count
// deep-links straight into that conversation on Ask TaxFlow), Documents (the
// old standalone ATO Correspondence tab is now just the "ATO-facing" bucket
// within Documents - approving one already landed it here, so a separate nav
// destination was two doors to the same list), and Templates (drafting
// instructions for every document type, in one place instead of only
// reachable per-document-type from inside the Ask TaxFlow save flow).
export default function WorkspacePage() {
  // Radix keeps every TabsContent mounted once rendered, so
  // WorkspaceClientsTable's own mount-time fetch only ever reflected
  // whatever was true the first time this page loaded - asking a fresh
  // question in Ask TaxFlow, then switching back to this already-mounted
  // Clients tab, showed stale (often zero) counts (accountant audit round
  // three, Priya/Michael). Tabs is controlled here so a fresh key is handed
  // to the table each time the Clients tab is actually selected, forcing its
  // fetch effect to re-run instead of trusting a fetch from whenever the
  // page happened to first load.
  const [clientsTabVisits, setClientsTabVisits] = useState(0);

  return (
    <Tabs
      defaultValue="clients"
      onValueChange={(value) => {
        if (value === "clients") setClientsTabVisits((n) => n + 1);
      }}
    >
      <TabsList>
        <TabsTrigger value="clients">Clients</TabsTrigger>
        <TabsTrigger value="documents">Documents</TabsTrigger>
        <TabsTrigger value="templates">Templates</TabsTrigger>
      </TabsList>
      <TabsContent value="clients">
        <WorkspaceClientsTable key={clientsTabVisits} />
      </TabsContent>
      <TabsContent value="documents">
        <DocumentsPage />
      </TabsContent>
      <TabsContent value="templates">
        <div className="max-w-2xl space-y-4">
          <div>
            <h1 className="text-xl font-semibold">Templates</h1>
            <p className="text-sm text-muted-foreground">
              Drafting instructions used to generate each document type from a saved answer.
            </p>
          </div>
          <DocumentTemplatesPanel />
        </div>
      </TabsContent>
    </Tabs>
  );
}
