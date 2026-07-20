import { makeResourceProxy } from "@/lib/api";

export const { GET, PATCH, DELETE } = makeResourceProxy("/ato-response");
