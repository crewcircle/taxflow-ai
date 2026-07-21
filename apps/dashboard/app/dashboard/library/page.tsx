"use client";

import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import KnowledgePage from "@/app/dashboard/knowledge/page";
import KnowledgeBasePage from "@/app/dashboard/knowledge-base/page";
import RegulatoryPage from "@/app/dashboard/regulatory/page";

// Consolidates "where does TaxFlow's knowledge come from" into two lanes
// instead of three separate nav destinations with three different mental
// models: your firm's own precedents (editable), and the shared reference
// library TaxFlow maintains (read-only) - with the live regulatory feed
// grouped into that second lane, since new arrivals there are just new
// additions to the same shared corpus, not a separate concept.
export default function LibraryPage() {
  // Deep-linkable so the regulatory bell (and any other "take me straight to
  // the reference lane" link) doesn't just land on the tab bar - read the
  // browser URL directly rather than useSearchParams so this component stays
  // reusable outside its own route (e.g. nowhere yet, but matches the
  // pattern already used by Documents' ?client= deep link).
  const [tab, setTab] = useState(() =>
    typeof window !== "undefined" && new URLSearchParams(window.location.search).get("tab") === "reference"
      ? "reference"
      : "firm"
  );

  return (
    <Tabs value={tab} onValueChange={setTab}>
      <TabsList>
        <TabsTrigger value="firm">Your firm&apos;s knowledge</TabsTrigger>
        <TabsTrigger value="reference">Shared reference library</TabsTrigger>
      </TabsList>
      <TabsContent value="firm">
        <KnowledgePage />
      </TabsContent>
      <TabsContent value="reference" className="space-y-6">
        <RegulatoryPage />
        <KnowledgeBasePage />
      </TabsContent>
    </Tabs>
  );
}
