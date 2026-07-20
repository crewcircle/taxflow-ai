"use client";

import { useState } from "react";
import { toast } from "sonner";

/**
 * Shared mutation helper for resource delete/edit across the dashboard.
 *
 * Wraps `fetch` in a sonner `toast.promise` (the Toaster is already mounted in
 * dashboard/layout.tsx) and calls `onSuccess` (typically the page's `load()` /
 * reload) on a 2xx response. Returns `true` on success, `false` otherwise, so
 * callers can e.g. close a dialog only when the mutation actually succeeded.
 */
export function useResourceMutation(opts: { onSuccess?: () => void } = {}): {
  remove: (url: string, successMsg: string) => Promise<boolean>;
  patch: (url: string, body: unknown, successMsg: string) => Promise<boolean>;
  pending: boolean;
} {
  const [pending, setPending] = useState(false);

  async function run(
    promise: Promise<Response>,
    successMsg: string
  ): Promise<boolean> {
    setPending(true);
    const wrapped = (async () => {
      const res = await promise;
      if (!res.ok) {
        // Prefer the backend's `detail` message (e.g. the 409 "in use" text).
        let detail = "Something went wrong";
        try {
          const data = await res.json();
          if (data?.detail) detail = data.detail;
        } catch {
          /* non-JSON body */
        }
        throw new Error(detail);
      }
      return res;
    })();

    toast.promise(wrapped, {
      loading: "Working…",
      success: successMsg,
      error: (err: Error) => err.message,
    });

    try {
      await wrapped;
      opts.onSuccess?.();
      return true;
    } catch {
      return false;
    } finally {
      setPending(false);
    }
  }

  return {
    remove: (url, successMsg) =>
      run(fetch(url, { method: "DELETE" }), successMsg),
    patch: (url, body, successMsg) =>
      run(
        fetch(url, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }),
        successMsg
      ),
    pending,
  };
}
