export interface Article {
  slug: string;
  title: string;
  dek: string;
  date: string;
  readMinutes: number;
  body: string[];
}

// Content sourced from the product's own knowledge base and test question
// bank (30 real AU tax questions, 15 ATO letter types) - not generic filler.
export const ARTICLES: Article[] = [
  {
    slug: "division-7a-triggers",
    title: "What actually triggers a Division 7A problem",
    dek: "It's not just cash withdrawals. Here's what to watch for before it becomes a deemed dividend.",
    date: "2026-06-15",
    readMinutes: 4,
    body: [
      "Division 7A gets blamed for a lot of things it doesn't actually cover, and missed for a lot of things it does. The short version: if a private company pays money to, lends money to, or forgives a debt owed by a shareholder or their associate, and there's no proper loan agreement in place, the ATO can treat it as an unfranked dividend - taxed in full, no franking credits to soften it.",
      "The cases that catch firms out aren't the obvious ones. A director using the company card for a personal expense and meaning to pay it back later. A trust distribution to a company that's never actually paid out, sitting as an unpaid present entitlement. A related company covering a shareholder's expenses because it was convenient at the time. None of these look like 'the company gave someone money' until you trace it through.",
      "The fix, when caught early, is usually a complying Division 7A loan agreement - a set interest rate, a maximum term, minimum yearly repayments. Done before the company's tax return is lodged for that year, it keeps the payment out of assessable income entirely. Done after, the options narrow fast.",
      "The part worth remembering: this isn't really about the size of the amount. A $2,000 personal expense run through the company account has the exact same mechanical trigger as a $200,000 loan. What matters is whether there's a complying agreement in place before lodgment - not how much money moved.",
    ],
  },
  {
    slug: "ato-letter-types",
    title: "The 15 ATO letters we see most, and what each one actually means",
    dek: "BAS discrepancy notice, garnishee notice, position paper - a plain-language guide to what's actually being asked.",
    date: "2026-06-22",
    readMinutes: 5,
    body: [
      "ATO letters are written to be legally precise, not to be easy to read under time pressure. Here's what the common ones actually mean, stripped of the formatting.",
      "A BAS discrepancy notice means the ATO's data-matching found a gap between what you reported and what third-party data (bank feeds, other lodgements) suggests. It's not an accusation - it's a request to explain or correct.",
      "An audit initiation letter means the ATO has decided to formally review a specific period or issue. It comes with a scope and a records request; the clock on your response starts from the letter date, not from when you get around to reading it.",
      "A garnishee notice is the most urgent of the lot - it means the ATO has already gone to a client's bank to intercept funds toward a debt. There's no grace period here; it needs a same-day call to the ATO debt line, not a same-week one.",
      "A position paper sets out the ATO's view on a disputed technical point before they finalise anything. It's an invitation to respond with a counter-argument and authority - silence gets read as agreement.",
      "A penalty notice means an administrative penalty has already been applied, usually for a lodgement or reporting shortfall. If reasonable care was taken, a remission request citing PS LA 2011/19 is worth lodging before assuming the penalty stands.",
      "The other nine types - lodgement reminders, audit completion notices, ABN cancellation proposals, GST registration queries, employer obligation reviews, lifestyle asset data-matching, taxable payments discrepancies, objection decisions, and payment plan requests - all follow the same pattern: a specific trigger, a specific timeframe, and a specific document that answers it. The letter almost always tells you what it wants, once you know what to look for.",
    ],
  },
  {
    slug: "beyond-the-ato-forum",
    title: "Why the ATO community forum isn't a research strategy",
    dek: "It's free, it's fast, and it's the wrong source for advice you're going to put your name on.",
    date: "2026-06-29",
    readMinutes: 3,
    body: [
      "The ATO's community forum is genuinely useful for a narrow set of things: confirming how a form field behaves, checking whether a portal outage is known, seeing if anyone else has hit the same lodgement error. It is not a source of binding guidance, and it's not written or reviewed the way a ruling is.",
      "Answers on the forum come from ATO staff acting informally, other practitioners guessing in good faith, or occasionally someone who's simply wrong with confidence. None of it can be cited to defend a position if the ATO later disagrees with the advice given under a client's name. A Private Binding Ruling can be cited. A Tax Ruling can be cited. A forum thread from 2023 cannot.",
      "The actual hierarchy, in order of how much weight it carries: legislation and case law first, then binding public rulings and determinations (TR, TD series), then practical compliance guidelines (PCG series) for the ATO's compliance approach, then private rulings for a specific taxpayer's facts. Forum posts, ATO webpages, and informal commentary sit below all of that - useful for orientation, not for the answer itself.",
      "The time cost is the other problem. A forum search returns a pile of loosely related threads with no way to tell which one is current, which was superseded by a later ruling, or which was simply never accurate. Going straight to the source material - the actual ruling, the actual section - is usually faster once you know where to look, and it's the only version that holds up if the position is ever challenged.",
    ],
  },
];

export function getArticle(slug: string): Article | undefined {
  return ARTICLES.find((a) => a.slug === slug);
}
