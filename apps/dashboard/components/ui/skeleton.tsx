import { cn } from "@/lib/utils";

// A pulsing placeholder block that preserves the shape of the content it
// stands in for - "Loading…" text collapses the layout and reads as "the
// page is empty," not "the page is working." Used to build list/row
// skeletons that hold the space the real content will occupy.
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn("animate-pulse rounded-md bg-muted", className)}
      {...props}
    />
  );
}

export { Skeleton };
