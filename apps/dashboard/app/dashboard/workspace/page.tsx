"use client";

import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ClientDirectory } from "@/components/ClientDirectory";
import DocumentsPage from "@/app/dashboard/documents/page";
import AtoResponsePage from "@/app/dashboard/ato-response/page";

// Consolidates Documents + ATO correspondence + a client directory into one
// destination: all three are "everything my firm has on file for a client" -
// approving an ATO response already lands it in the Documents list today, so
// splitting them into separate nav items was multiple doors to one job. Each
// resource tab renders the real, untouched page component (no logic
// duplicated/rewritten) so neither workflow's behaviour changes - only where
// you find it does. Clients is new: a real browsable list (name, work on
// file, last activity) instead of only the sidebar's "highlight by client"
// text filter, which doesn't scale once a firm has hundreds of clients.
export default function WorkspacePage() {
  const [tab, setTab] = useState("documents");

  function goToClientDocuments(name: string) {
    const url = new URL(window.location.href);
    url.searchParams.set("client", name);
    window.history.replaceState(null, "", url);
    setTab("documents");
  }

  return (
    <Tabs value={tab} onValueChange={setTab}>
      <TabsList>
        <TabsTrigger value="documents">Documents</TabsTrigger>
        <TabsTrigger value="ato">ATO correspondence</TabsTrigger>
        <TabsTrigger value="clients">Clients</TabsTrigger>
      </TabsList>
      <TabsContent value="documents">
        <DocumentsPage />
      </TabsContent>
      <TabsContent value="ato">
        <AtoResponsePage />
      </TabsContent>
      <TabsContent value="clients">
        <ClientDirectory onSelectClient={goToClientDocuments} />
      </TabsContent>
    </Tabs>
  );
}
