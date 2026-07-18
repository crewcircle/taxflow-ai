"use client";

import { createContext, useContext, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";

interface QueryPaneState {
  historyOpen: boolean;
  setHistoryOpen: Dispatch<SetStateAction<boolean>>;
  sourcesOpen: boolean;
  setSourcesOpen: Dispatch<SetStateAction<boolean>>;
}

// Lets the global DashboardHeader (rendered by the server layout, outside the
// query page's own component tree) and the Ask TaxFlow page share the same
// "Hide questions" / "Hide sources" toggle state.
const QueryPaneContext = createContext<QueryPaneState | null>(null);

export function QueryPaneProvider({ children }: { children: ReactNode }) {
  const [historyOpen, setHistoryOpen] = useState(true);
  const [sourcesOpen, setSourcesOpen] = useState(true);

  return (
    <QueryPaneContext.Provider value={{ historyOpen, setHistoryOpen, sourcesOpen, setSourcesOpen }}>
      {children}
    </QueryPaneContext.Provider>
  );
}

export function useQueryPane() {
  const ctx = useContext(QueryPaneContext);
  if (!ctx) throw new Error("useQueryPane must be used within QueryPaneProvider");
  return ctx;
}
