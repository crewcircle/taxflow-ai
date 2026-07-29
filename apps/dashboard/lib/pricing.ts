// Shared by the public /pricing page and the in-app /upgrade page so the
// two can't drift out of sync.
export const TIERS = [
  {
    id: "starter",
    name: "Starter",
    price: "$99",
    period: "/month + GST",
    highlighted: false,
    features: [
      "1,000 research queries / month",
      "100 documents / month",
      "Unlimited staff seats with role-based permissions",
      "ATO correspondence module",
      "Email support",
    ],
  },
  {
    id: "professional",
    name: "Professional",
    price: "$199",
    period: "/month + GST",
    highlighted: true,
    features: [
      "Unlimited research queries",
      "Unlimited documents",
      "Unlimited staff seats with role-based permissions",
      "ATO correspondence module",
      "Firm knowledge base",
      "Regulatory alerts",
      "Priority support",
    ],
  },
] as const;
