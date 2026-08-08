// Shared between the documents list and the document detail page - was
// previously copy-pasted in both places, so adding a new document status
// only updated one of the two copies unless the author remembered the other.
export const DOCUMENT_STATUS_VARIANT: Record<string, "default" | "secondary" | "outline"> = {
  draft: "outline",
  approved: "secondary",
  sent: "default",
  archived: "outline",
};
