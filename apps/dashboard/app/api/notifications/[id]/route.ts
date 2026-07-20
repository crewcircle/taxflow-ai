import { makeResourceProxy } from "@/lib/api";

export const { DELETE } = makeResourceProxy("/notifications", { DELETE: true });
