import Link from "next/link";

function DemoBadge() {
  return <span className="ml-2 rounded bg-neutral-200 px-1.5 py-0.5 text-xs">DEMO</span>;
}

export default function DashboardOverviewPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Overview</h1>

      <div className="grid grid-cols-3 gap-4">
        <div className="rounded border p-4">
          <p className="text-sm text-neutral-500">
            Queries today
            <DemoBadge />
          </p>
          <p className="text-2xl font-semibold">7</p>
        </div>
        <div className="rounded border p-4">
          <p className="text-sm text-neutral-500">
            Documents this week
            <DemoBadge />
          </p>
          <p className="text-2xl font-semibold">3</p>
        </div>
        <div className="rounded border p-4">
          <p className="text-sm text-neutral-500">
            Trial days remaining
            <DemoBadge />
          </p>
          <p className="text-2xl font-semibold">28</p>
        </div>
      </div>

      <Link
        href="/dashboard/query"
        className="inline-block rounded bg-black px-4 py-2 text-sm text-white"
      >
        Quick question →
      </Link>
    </div>
  );
}
