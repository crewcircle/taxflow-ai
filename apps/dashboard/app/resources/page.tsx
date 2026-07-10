import Link from "next/link";
import { MarketingHeader } from "@/components/MarketingHeader";
import { MarketingFooter } from "@/components/MarketingFooter";
import { ARTICLES } from "@/lib/resources";

export default function ResourcesPage() {
  return (
    <>
      <MarketingHeader />
      <main className="flex-1 bg-background px-6 py-20">
        <div className="mx-auto max-w-3xl">
          <span className="mb-3 block text-xs font-semibold uppercase tracking-widest text-accent">
            Resources
          </span>
          <h1 className="mb-4 text-3xl font-bold text-foreground md:text-4xl">
            Plain-language notes on the things that trip firms up
          </h1>
          <p className="mb-14 text-lg text-muted-foreground">
            No jargon, no filler - just the parts that are actually useful.
          </p>

          <div className="space-y-10">
            {ARTICLES.map((article) => (
              <div key={article.slug} className="border-b border-border pb-10 last:border-b-0">
                <p className="mb-2 text-sm text-muted-foreground">
                  {new Date(article.date).toLocaleDateString("en-AU", {
                    year: "numeric",
                    month: "long",
                    day: "numeric",
                  })}{" "}
                  · {article.readMinutes} min read
                </p>
                <h2 className="mb-2 text-2xl font-semibold text-foreground">{article.title}</h2>
                <p className="mb-4 text-muted-foreground">{article.dek}</p>
                <Link
                  href={`/resources/${article.slug}`}
                  className="font-medium text-accent hover:underline"
                >
                  Read more →
                </Link>
              </div>
            ))}
          </div>
        </div>
      </main>
      <MarketingFooter />
    </>
  );
}
