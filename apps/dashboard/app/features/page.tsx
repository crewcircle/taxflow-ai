import Link from "next/link";
import {
  BookOpen,
  FileText,
  MessageSquare,
  ScrollText,
  ShieldCheck,
  Users,
  Briefcase,
} from "lucide-react";
import { MarketingHeader } from "@/components/MarketingHeader";
import { MarketingFooter } from "@/components/MarketingFooter";
import { Button } from "@/components/ui/button";

const MODULES = [
  {
    icon: MessageSquare,
    title: "Research & Advisory",
    description:
      "Ask a question in plain English. The answer is built only from real ATO rulings, determinations and legislation - never from guesswork - with every claim linked to its source.",
    details: [
      "Streams in as it's written, so you're not staring at a spinner",
      "Numbered references you can click straight through to the source document",
      "Escalates to a stronger model automatically on harder questions",
    ],
  },
  {
    icon: ShieldCheck,
    title: "Answer verification",
    description:
      "Every answer is checked after it's written. A second pass compares each claim against the source material and flags anything that isn't fully backed up.",
    details: [
      "Flagged claims are underlined right where they appear in the answer - click to see why",
      "Specific issues are listed, not just a vague warning",
      "Runs automatically - nothing to switch on",
    ],
  },
  {
    icon: Users,
    title: "Team & permissions",
    description:
      "Bring your whole team in, not just one shared login. Owner, Reviewer, and Staff roles with a built-in approval gate - Staff can draft, but only an Owner or Reviewer can approve and finalise it as firm work product.",
    details: [
      "Unlimited staff seats on every plan",
      "@mention a teammate on any answer or document and they get a real notification",
      "A human always signs off before anything leaves the firm",
    ],
  },
  {
    icon: Briefcase,
    title: "Client & engagement tracking",
    description:
      "Every question is attributed to a specific client and a specific engagement, so a client with a return, an ATO audit, and a structuring question in progress at the same time never gets their history mixed up.",
    details: [
      "One client can run multiple concurrent engagements as separate threads",
      "Search across every client, conversation, and document from one Cmd+K box",
      "Nothing gets filed against the wrong matter",
    ],
  },
  {
    icon: ScrollText,
    title: "ATO Correspondence",
    description:
      "Upload an ATO letter as a PDF. We work out what type it is - BAS discrepancy, audit notice, penalty notice, and more - and draft a response.",
    details: [
      "Covers 15 common ATO letter types",
      "Comes with an evidence checklist and a recommended timeline",
      "Drafts a formal reply you can review and send",
    ],
  },
  {
    icon: FileText,
    title: "Document generation",
    description:
      "Turn a research answer or ATO response into a properly formatted document, ready to download and send.",
    details: ["Exports to Word (.docx)", "Consistent formatting across your firm", "Kept in your document library"],
  },
  {
    icon: BookOpen,
    title: "Firm knowledge",
    description:
      "Upload your own precedents, templates, or internal guidance. Research answers blend these in alongside the public knowledge base - never shared with other firms.",
    details: [
      "Supports PDF, Word, and plain text",
      "Weighted higher than public sources for your own questions",
      "Fully isolated per firm",
    ],
  },
];

export default function FeaturesPage() {
  return (
    <>
      <MarketingHeader />
      <main className="flex-1 bg-background px-6 py-20">
        <div className="mx-auto max-w-3xl text-center">
          <span className="mb-3 block text-xs font-semibold uppercase tracking-widest text-accent">
            What&apos;s included
          </span>
          <h1 className="mb-4 text-3xl font-bold text-foreground md:text-4xl">
            Every module, plainly explained
          </h1>
          <p className="text-lg text-muted-foreground">
            No vague promises - here&apos;s exactly what each part of TaxFlow does.
          </p>
        </div>

        <div className="mx-auto mt-16 max-w-4xl space-y-6">
          {MODULES.map((mod) => (
            <div
              key={mod.title}
              className="rounded-xl border border-border bg-card p-8 transition-all hover:border-accent/20 hover:shadow-md"
            >
              <div className="flex flex-col gap-6 md:flex-row md:items-start">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-accent/10 text-accent">
                  <mod.icon className="h-6 w-6" />
                </div>
                <div>
                  <h2 className="mb-2 text-xl font-bold text-foreground">{mod.title}</h2>
                  <p className="mb-4 text-sm leading-relaxed text-muted-foreground">{mod.description}</p>
                  <ul className="space-y-1.5">
                    {mod.details.map((d) => (
                      <li key={d} className="flex items-start gap-2 text-sm text-muted-foreground">
                        <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-accent" />
                        {d}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="mx-auto mt-20 max-w-2xl text-center">
          <h2 className="mb-4 text-2xl font-bold text-foreground">See it on a real question</h2>
          <div className="flex flex-col justify-center gap-4 sm:flex-row">
            <Button asChild size="lg" className="bg-accent text-accent-foreground hover:opacity-90">
              <Link href="/signup">Start your free trial</Link>
            </Button>
            <Button asChild size="lg" variant="outline">
              <Link href="/login">Try the live demo</Link>
            </Button>
          </div>
        </div>
      </main>
      <MarketingFooter />
    </>
  );
}
