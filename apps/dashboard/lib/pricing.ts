// Shared by the public /pricing page and the in-app /upgrade page so the
// two can't drift out of sync.
export const TIERS = [
  {
    id: "starter",
    name: "Starter",
    price: "$2,400",
    period: "/year + GST",
    highlighted: false,
    features: [
      "300 research queries / month",
      "50 documents / month",
      "ATO correspondence module",
      "Email support",
    ],
  },
  {
    id: "professional",
    name: "Professional",
    price: "$6,000",
    period: "/year + GST",
    highlighted: true,
    features: [
      "Unlimited research queries",
      "Unlimited documents",
      "ATO correspondence module",
      "Firm knowledge base",
      "Regulatory alerts",
      "Priority support",
    ],
  },
] as const;
