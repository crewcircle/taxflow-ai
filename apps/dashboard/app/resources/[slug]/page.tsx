import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { MarketingHeader } from "@/components/MarketingHeader";
import { MarketingFooter } from "@/components/MarketingFooter";
import { ARTICLES, getArticle } from "@/lib/resources";

export function generateStaticParams() {
  return ARTICLES.map((a) => ({ slug: a.slug }));
}

export default async function ArticlePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const article = getArticle(slug);
  if (!article) notFound();

  return (
    <>
      <MarketingHeader />
      <main className="flex-1 bg-background px-6 py-20">
        <div className="mx-auto max-w-2xl">
          <Link
            href="/resources"
            className="mb-8 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-4" />
            All resources
          </Link>

          <p className="mb-2 text-sm text-muted-foreground">
            {new Date(article.date).toLocaleDateString("en-AU", {
              year: "numeric",
              month: "long",
              day: "numeric",
            })}{" "}
            · {article.readMinutes} min read
          </p>
          <h1 className="mb-6 text-3xl font-bold text-foreground md:text-4xl">{article.title}</h1>

          <div className="space-y-5 text-base leading-relaxed text-muted-foreground">
            {article.body.map((paragraph, i) => (
              <p key={i}>{paragraph}</p>
            ))}
          </div>

          <div className="mt-12 rounded-xl border border-border bg-muted/30 p-6">
            <p className="mb-4 text-sm font-medium text-foreground">
              Want an answer like this on your own question, with sources checked?
            </p>
            <Link href="/signup" className="font-medium text-accent hover:underline">
              Start your free trial →
            </Link>
          </div>
        </div>
      </main>
      <MarketingFooter />
    </>
  );
}
