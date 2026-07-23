import { makeResourceProxy } from "@/lib/api";

export const { PATCH, DELETE } = makeResourceProxy("/staff", { PATCH: true, DELETE: true });
