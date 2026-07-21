"use client";

import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import DocumentsPage from "@/app/dashboard/documents/page";
import AtoResponsePage from "@/app/dashboard/ato-response/page";

// Consolidates Documents + ATO correspondence into one destination: both are
// "everything my firm has generated or is working through for a client" -
// approving an ATO response already lands it in the Documents list today, so
// splitting them into two nav items was two doors to one job. Each tab
// renders the real, untouched page component (no logic duplicated/rewritten)
// so neither workflow's behaviour changes - only where you find it does.
export default function WorkspacePage() {
  const [tab, setTab] = useState("documents");

  return (
    <Tabs value={tab} onValueChange={setTab}>
      <TabsList>
        <TabsTrigger value="documents">Documents</TabsTrigger>
        <TabsTrigger value="ato">ATO correspondence</TabsTrigger>
      </TabsList>
      <TabsContent value="documents">
        <DocumentsPage />
      </TabsContent>
      <TabsContent value="ato">
        <AtoResponsePage />
      </TabsContent>
    </Tabs>
  );
}
