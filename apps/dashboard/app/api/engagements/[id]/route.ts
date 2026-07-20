import { makeResourceProxy } from "@/lib/api";

export const { GET } = makeResourceProxy("/engagements", { GET: true });
