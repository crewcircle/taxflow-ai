import Link from "next/link";
import { MarketingHeader } from "@/components/MarketingHeader";
import { MarketingFooter } from "@/components/MarketingFooter";
import { Button } from "@/components/ui/button";

export default function AboutPage() {
  return (
    <>
      <MarketingHeader />
      <main className="flex-1 bg-background px-6 py-20">
        <div className="mx-auto max-w-2xl">
          <span className="mb-3 block text-xs font-semibold uppercase tracking-widest text-accent">
            About TaxFlow
          </span>
          <h1 className="mb-6 text-3xl font-bold text-foreground md:text-4xl">
            Why we built this
          </h1>

          <div className="space-y-5 text-base leading-relaxed text-muted-foreground">
            <p>
              TaxFlow is built by <strong className="text-foreground">CrewCircle</strong>, a Sydney-based
              team that builds practical software for Australian small businesses - no enterprise
              sales process, no jargon, just tools that do the job.
            </p>
            <p>
              We kept hearing the same thing from accountants: tax research eats hours every week,
              and most of that time is spent digging through the ATO site or old memos looking for
              the one ruling that actually answers the question. Meanwhile, ATO letters pile up
              because working out what they actually require takes almost as long as answering them.
            </p>
            <p>
              So we built TaxFlow to do both properly: research answers built only from real
              rulings and legislation, checked against those sources before you see them - and an
              ATO correspondence tool that reads a letter and tells you what it actually means.
            </p>
            <p>
              It&apos;s one product from the same team behind{" "}
              <a
                href="https://crewcircle.com.au"
                target="_blank"
                rel="noreferrer"
                className="font-medium text-accent hover:underline"
              >
                crewcircle.com.au
              </a>
              , applying the same idea to accounting firms: software that actually sorts the boring
              stuff out.
            </p>
          </div>

          <div className="mt-12 border-t border-border pt-8">
            <h2 className="mb-3 text-xl font-bold text-foreground">Where your data lives</h2>
            <div className="space-y-4 text-base leading-relaxed text-muted-foreground">
              <p>
                Your practice data - client records, documents, question history - is stored and
                hosted in Australia, isolated per firm at the database level. Firm-uploaded
                knowledge is never used to answer another firm&apos;s questions.
              </p>
              <p>
                To generate an answer, the text of your question is sent to Anthropic&apos;s and
                OpenAI&apos;s AI models under their standard API terms, which is how every AI
                product in this category works today. We don&apos;t claim your questions never
                leave Australia, because that wouldn&apos;t be true - we&apos;d rather tell you
                exactly what happens than make a claim that doesn&apos;t hold up. If your firm
                needs a stricter data-processing arrangement for a specific engagement,{" "}
                <Link href="/contact" className="font-medium text-accent hover:underline">
                  get in touch
                </Link>{" "}
                and we&apos;ll talk through the options.
              </p>
            </div>
          </div>

          <div className="mt-12 flex flex-col gap-4 sm:flex-row">
            <Button asChild size="lg" className="bg-accent text-accent-foreground hover:opacity-90">
              <Link href="/signup">Start your free trial</Link>
            </Button>
            <Button asChild size="lg" variant="outline">
              <Link href="/contact">Get in touch</Link>
            </Button>
          </div>
        </div>
      </main>
      <MarketingFooter />
    </>
  );
}
