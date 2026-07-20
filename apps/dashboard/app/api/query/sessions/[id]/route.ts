import { makeResourceProxy } from "@/lib/api";

export const { PATCH, DELETE } = makeResourceProxy("/query/sessions", {
  PATCH: true,
  DELETE: true,
});
