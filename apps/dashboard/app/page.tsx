import Link from "next/link";
import { redirect } from "next/navigation";
import { CheckCircle2, FileWarning, MessageSquare, ShieldCheck } from "lucide-react";
import { createClient } from "@/lib/supabase/server";
import { MarketingHeader } from "@/components/MarketingHeader";
import { MarketingFooter } from "@/components/MarketingFooter";
import { DemoCallout } from "@/components/DemoCallout";
import { Button } from "@/components/ui/button";

const FEATURES = [
  {
    icon: MessageSquare,
    title: "Ask a tax question, get a cited answer",
    description:
      "Type a question in plain English. Get an answer built only from real ATO rulings and legislation, with every claim linked back to its source.",
  },
  {
    icon: FileWarning,
    title: "Upload an ATO letter, get a plan",
    description:
      "We read the letter, work out what type it is, and draft a response - plus a checklist of what evidence to gather before you reply.",
  },
  {
    icon: ShieldCheck,
    title: "Every answer gets checked",
    description:
      "After the answer is written, a second check compares each claim against the source material and flags anything that isn't fully backed up.",
  },
];

const STEPS = [
  {
    step: "1",
    title: "Ask your question",
    description: "Type it in like you would to a colleague. No special syntax, no forms.",
  },
  {
    step: "2",
    title: "Get a sourced answer in seconds",
    description: "The answer streams in with numbered references you can click through to the source.",
  },
  {
    step: "3",
    title: "See it checked",
    description: "A moment later, a badge shows whether every claim held up against the source material.",
  },
];

export default async function Home() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (user) {
    redirect("/dashboard");
  }

  return (
    <>
      <MarketingHeader />
      <main className="flex-1 bg-background">
        {/* Hero */}
        <section className="relative overflow-hidden px-6 py-24 md:py-32">
          <div className="absolute inset-0 bg-gradient-to-br from-accent/[0.03] via-background to-primary/[0.03]" />
          <div className="absolute top-0 right-0 h-[500px] w-[500px] -translate-y-1/2 translate-x-1/3 rounded-full bg-accent/[0.04] blur-3xl" />

          <div className="relative mx-auto max-w-3xl text-center">
            <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-accent/15 bg-accent/5 px-4 py-2 text-sm font-medium text-accent">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-accent" />
              </span>
              Built for Australian accounting firms
            </div>

            <h1 className="mb-6 text-4xl font-bold leading-[1.1] tracking-tight text-foreground md:text-5xl lg:text-[3.5rem]">
              Tax research that actually{" "}
              <span className="text-accent">shows its working.</span>
            </h1>

            <p className="mx-auto mb-10 max-w-xl text-lg leading-relaxed text-muted-foreground md:text-xl">
              Stop digging through the ATO site and old memos. Ask TaxFlow a question, get an
              answer built from real rulings and legislation - with every source linked, and
              every claim checked before you see it.
            </p>

            <div className="flex flex-col justify-center gap-4 sm:flex-row">
              <Button asChild size="lg" className="bg-accent text-accent-foreground hover:opacity-90">
                <Link href="/signup">Start your free trial</Link>
              </Button>
              <Button asChild size="lg" variant="outline">
                <Link href="/pricing">See pricing</Link>
              </Button>
            </div>

            <DemoCallout />
          </div>
        </section>

        {/* Features */}
        <section className="bg-muted/30 px-6 py-24">
          <div className="mx-auto max-w-6xl">
            <div className="mb-14 max-w-2xl">
              <span className="mb-3 block text-xs font-semibold uppercase tracking-widest text-accent">
                How it helps
              </span>
              <h2 className="mb-4 text-3xl font-bold text-foreground md:text-4xl">
                What TaxFlow actually does
              </h2>
              <p className="text-lg leading-relaxed text-muted-foreground">
                Three things, done properly, instead of a hundred things done half-heartedly.
              </p>
            </div>

            <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
              {FEATURES.map((feature) => (
                <div
                  key={feature.title}
                  className="rounded-xl border border-border bg-card p-8 transition-all hover:border-accent/20 hover:shadow-md"
                >
                  <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-xl bg-accent/10 text-accent">
                    <feature.icon className="h-6 w-6" />
                  </div>
                  <h3 className="mb-3 text-xl font-bold text-foreground">{feature.title}</h3>
                  <p className="text-sm leading-relaxed text-muted-foreground">
                    {feature.description}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* How it works */}
        <section className="px-6 py-24">
          <div className="mx-auto max-w-4xl">
            <div className="mb-14 text-center">
              <span className="mb-3 block text-xs font-semibold uppercase tracking-widest text-accent">
                How it works
              </span>
              <h2 className="text-3xl font-bold text-foreground md:text-4xl">Three steps, no training required</h2>
            </div>

            <div className="grid grid-cols-1 gap-8 md:grid-cols-3">
              {STEPS.map((s) => (
                <div key={s.step} className="text-center">
                  <div className="mx-auto mb-4 flex h-10 w-10 items-center justify-center rounded-full bg-primary text-sm font-bold text-primary-foreground">
                    {s.step}
                  </div>
                  <h3 className="mb-2 text-lg font-bold text-foreground">{s.title}</h3>
                  <p className="text-sm leading-relaxed text-muted-foreground">{s.description}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Trust strip */}
        <section className="border-y border-border bg-muted/30 px-6 py-16">
          <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-center gap-x-12 gap-y-4">
            {[
              "Real ATO rulings and legislation, not training-data guesses",
              "Every answer checked against its sources before you see it",
              "Built and hosted in Australia",
            ].map((item) => (
              <div key={item} className="flex items-center gap-2 text-sm text-muted-foreground">
                <CheckCircle2 className="h-4 w-4 shrink-0 text-accent" />
                {item}
              </div>
            ))}
          </div>
        </section>

        {/* Resources teaser */}
        <section className="px-6 py-24">
          <div className="mx-auto max-w-4xl text-center">
            <span className="mb-3 block text-xs font-semibold uppercase tracking-widest text-accent">
              Worth a read
            </span>
            <h2 className="mb-4 text-3xl font-bold text-foreground md:text-4xl">From the resources page</h2>
            <p className="mb-8 text-lg text-muted-foreground">
              Plain-language notes on the things that actually trip firms up.
            </p>
            <Button asChild variant="outline">
              <Link href="/resources">Browse resources</Link>
            </Button>
          </div>
        </section>

        {/* Final CTA */}
        <section className="bg-primary px-6 py-24 text-primary-foreground">
          <div className="mx-auto max-w-2xl text-center">
            <h2 className="mb-4 text-3xl font-bold md:text-4xl">Try it on a real question</h2>
            <p className="mb-8 text-lg text-primary-foreground/70">
              30 days free, 100 questions, no card required. Or try the live demo right now -
              no signup at all.
            </p>
            <div className="flex flex-col justify-center gap-4 sm:flex-row">
              <Button asChild size="lg" className="bg-accent text-accent-foreground hover:opacity-90">
                <Link href="/signup">Start your free trial</Link>
              </Button>
              <Button asChild size="lg" variant="outline" className="border-primary-foreground/20 text-primary-foreground hover:bg-primary-foreground/10">
                <Link href="/login">Try the live demo</Link>
              </Button>
            </div>
          </div>
        </section>
      </main>
      <MarketingFooter />
    </>
  );
}
