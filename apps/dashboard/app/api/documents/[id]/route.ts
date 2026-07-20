import { makeResourceProxy } from "@/lib/api";

export const { GET, PATCH, DELETE } = makeResourceProxy("/documents");
