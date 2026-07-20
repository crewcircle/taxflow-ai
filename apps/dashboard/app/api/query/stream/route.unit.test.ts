import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// R1 regression (proxy-level): the Next stream route must forward the
// engagement_id query param to the backend. Before the fix it read only
// client_ref + session_id, so a UI-selected engagement was silently dropped and
// the query persisted with engagement_id = NULL.

// Mock the Supabase server client so the route sees an authenticated session.
vi.mock("@/lib/supabase/server", () => ({
  createClient: async () => ({
    auth: {
      getSession: async () => ({
        data: { session: { access_token: "test-token" } },
      }),
    },
  }),
}));

import { GET } from "@/app/api/query/stream/route";

function makeRequest(query: Record<string, string>) {
  const url = new URL("http://localhost/api/query/stream");
  for (const [k, v] of Object.entries(query)) url.searchParams.set(k, v);
  // The route only reads `nextUrl`, so a minimal shape is enough.
  return { nextUrl: url } as unknown as import("next/server").NextRequest;
}

describe("GET /api/query/stream proxy", () => {
  beforeEach(() => {
    process.env.NEXT_PUBLIC_API_URL = "http://backend.test";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("data: [DONE]\n\n", { status: 200 }))
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("forwards engagement_id (plus question/client_ref/session_id) to the backend", async () => {
    await GET(
      makeRequest({
        question: "What is Div 7A?",
        client_ref: "Acme Pty Ltd",
        session_id: "sess-1",
        engagement_id: "eng-1",
      })
    );

    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const calledUrl = new URL(fetchMock.mock.calls[0][0] as URL);
    expect(calledUrl.pathname).toBe("/query/stream");
    expect(calledUrl.searchParams.get("engagement_id")).toBe("eng-1");
    expect(calledUrl.searchParams.get("client_ref")).toBe("Acme Pty Ltd");
    expect(calledUrl.searchParams.get("session_id")).toBe("sess-1");
    expect(calledUrl.searchParams.get("question")).toBe("What is Div 7A?");
  });

  it("omits engagement_id when none is supplied", async () => {
    await GET(makeRequest({ question: "hi" }));
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const calledUrl = new URL(fetchMock.mock.calls[0][0] as URL);
    expect(calledUrl.searchParams.has("engagement_id")).toBe(false);
  });
});
