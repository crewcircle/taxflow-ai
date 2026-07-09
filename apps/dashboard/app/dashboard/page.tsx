import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

function DemoBadge() {
  return (
    <Badge variant="outline" className="ml-2 text-[10px] text-muted-foreground">
      DEMO
    </Badge>
  );
}

const STATS = [
  { label: "Queries today", value: "7" },
  { label: "Documents this week", value: "3" },
  { label: "Trial days remaining", value: "28" },
];

export default function DashboardOverviewPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Overview</h1>

      <div className="grid grid-cols-3 gap-4">
        {STATS.map((stat) => (
          <Card key={stat.label}>
            <CardHeader className="pb-0">
              <p className="flex items-center text-sm text-muted-foreground">
                {stat.label}
                <DemoBadge />
              </p>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-semibold">{stat.value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <Button asChild>
        <Link href="/dashboard/query">Quick question →</Link>
      </Button>
    </div>
  );
}
