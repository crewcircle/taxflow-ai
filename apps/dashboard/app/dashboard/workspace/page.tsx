"use client";

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
  return (
    <Tabs defaultValue="clients">
      <TabsList>
        <TabsTrigger value="clients">Clients</TabsTrigger>
        <TabsTrigger value="documents">Documents</TabsTrigger>
        <TabsTrigger value="templates">Templates</TabsTrigger>
      </TabsList>
      <TabsContent value="clients">
        <WorkspaceClientsTable />
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
