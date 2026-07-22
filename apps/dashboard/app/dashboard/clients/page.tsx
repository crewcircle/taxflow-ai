import { redirect } from "next/navigation";

// The client/engagement directory this page used to own now lives in the
// "Clients & conversations" sidebar on the Ask TaxFlow page - redirect old
// links/bookmarks there instead of a dead nav destination.
export default function ClientsPage() {
  redirect("/dashboard/query");
}
