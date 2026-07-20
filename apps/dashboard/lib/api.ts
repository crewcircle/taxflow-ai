import { createClient } from "@/lib/supabase/server";

// Server-side proxy helper: forwards a request to the FastAPI backend with the
// current user's Supabase access token, and mirrors the response back verbatim.
export async function proxyToBackend(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const backendResponse = await fetch(`${process.env.NEXT_PUBLIC_API_URL}${path}`, {
      ...init,
      headers: {
        ...init.headers,
        Authorization: `Bearer ${session.access_token}`,
      },
    });
    return backendResponse;
  } catch {
    return Response.json(
      { detail: "Service unavailable - please try again shortly" },
      { status: 502 }
    );
  }
}

// fetch() on the Node runtime transparently decompresses gzip/br response
// bodies but leaves content-encoding/content-length on the Headers object
// untouched. Forwarding those headers verbatim tells the browser it's
// receiving a compressed body when it isn't, which fails with
// ERR_CONTENT_DECODING_FAILED. Strip them before mirroring a backend
// response back to the client.
export function forwardResponse(response: Response): Response {
  const headers = new Headers(response.headers);
  headers.delete("content-encoding");
  headers.delete("content-length");
  return new Response(response.body, { status: response.status, headers });
}

// Next.js dynamic `[id]` route context: the id segment arrives as a Promise.
type RouteContext = { params: Promise<{ id: string }> };
type RouteHandler = (request: Request, context: RouteContext) => Promise<Response>;

/**
 * Factory for the near-identical `[id]` resource proxy routes. Every one of
 * them forwards GET/PATCH/DELETE for `<basePath>/<id>` to the backend with the
 * same `proxyToBackend`/`forwardResponse` behaviour — only the base path and
 * which verbs are enabled differ. Pass the methods you want; a route file then
 * collapses to `export const { PATCH, DELETE } = makeResourceProxy("/documents")`.
 */
export function makeResourceProxy(
  basePath: string,
  methods: { GET?: boolean; PATCH?: boolean; DELETE?: boolean } = {
    GET: true,
    PATCH: true,
    DELETE: true,
  }
): { GET?: RouteHandler; PATCH?: RouteHandler; DELETE?: RouteHandler } {
  const handlers: { GET?: RouteHandler; PATCH?: RouteHandler; DELETE?: RouteHandler } = {};

  if (methods.GET) {
    handlers.GET = async (_request, { params }) => {
      const { id } = await params;
      return forwardResponse(await proxyToBackend(`${basePath}/${id}`));
    };
  }
  if (methods.PATCH) {
    handlers.PATCH = async (request, { params }) => {
      const { id } = await params;
      const body = await request.text();
      return forwardResponse(
        await proxyToBackend(`${basePath}/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body,
        })
      );
    };
  }
  if (methods.DELETE) {
    handlers.DELETE = async (_request, { params }) => {
      const { id } = await params;
      return forwardResponse(
        await proxyToBackend(`${basePath}/${id}`, { method: "DELETE" })
      );
    };
  }

  return handlers;
}
