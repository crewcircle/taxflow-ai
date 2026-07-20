/**
 * Analytics dashboard E2E: verifies the operator-only pipeline-analytics page
 * renders its drift banner, KPI cards, charts and model table from a MOCKED
 * /api/admin/stats response, and that the nav link routes to it.
 *
 * Deliberately does NOT require a live backend - the /api/admin/stats route is
 * intercepted with page.route(), so the whole page can be exercised offline.
 * Auth mirrors full-flow.spec.ts (admin.generateLink + verifyOtp -> the exact
 * @supabase/ssr cookie), so the server sees a real session; ADMIN_EMAILS must
 * include the test email for the operator nav link and route to be allowed.
 *
 * NOT part of CI (creates a real account + needs Supabase service creds). Run:
 *   doppler run --project taxflow --config prd -- npx playwright test analytics
 */
import { test, expect, type Page } from "@playwright/test";
import { createClient } from "@supabase/supabase-js";

const TEST_EMAIL = process.env.ANALYTICS_ADMIN_EMAIL ?? "hanan@crewcircle.com.au";

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required env var ${name} - run this via doppler`);
  return value;
}

async function completeMagicLinkLogin(page: Page, email: string) {
  const supabaseUrl = requireEnv("SUPABASE_URL");
  const supabaseAdmin = createClient(supabaseUrl, requireEnv("SUPABASE_SERVICE_ROLE_KEY"));
  const { data: linkData, error: linkError } = await supabaseAdmin.auth.admin.generateLink({
    type: "magiclink",
    email,
  });
  const hashedToken = linkData?.properties?.hashed_token;
  if (linkError || !hashedToken) {
    throw new Error(`Could not generate magic link for ${email}: ${linkError?.message}`);
  }

  const supabaseAnon = createClient(supabaseUrl, requireEnv("SUPABASE_ANON_KEY"));
  const { data: otpData, error: otpError } = await supabaseAnon.auth.verifyOtp({
    type: "magiclink",
    token_hash: hashedToken,
  });
  if (otpError || !otpData?.session) {
    throw new Error(`Could not verify OTP for ${email}: ${otpError?.message}`);
  }

  const projectRef = new URL(supabaseUrl).hostname.split(".")[0];
  const cookieValue =
    "base64-" + Buffer.from(JSON.stringify(otpData.session), "utf-8").toString("base64url");
  const baseURL = test.info().project.use.baseURL as string;
  await page.context().addCookies([
    {
      name: `sb-${projectRef}-auth-token`,
      value: cookieValue,
      domain: new URL(baseURL).hostname,
      path: "/",
      sameSite: "Lax",
      secure: true,
      httpOnly: false,
    },
  ]);
}

// A snapshot row matching the backend /admin/stats contract.
function snapshot(overrides: Record<string, unknown> = {}) {
  return {
    id: "snap-1",
    window_start: "2026-07-13",
    window_end: "2026-07-20",
    baseline_start: "2026-06-22",
    baseline_end: "2026-07-13",
    metrics: { overall: { verification_failure_rate: 0.129, feedback_down_rate: 0.094 } },
    diff: { deltas: {}, regressions: [], has_regressions: false },
    has_regressions: false,
    created_at: "2026-07-20T06:00:00Z",
    ...overrides,
  };
}

function buildStats({ drift }: { drift: boolean }) {
  const by_day = Array.from({ length: 14 }, (_, i) => ({
    day: `2026-07-${String(i + 6).padStart(2, "0")}`,
    query_volume: 60 + i * 3,
    avg_latency_ms: 3800 + i * 20,
    avg_cost_usd: 0.02 + i * 0.001,
  }));
  const regressions = drift
    ? ["feedback_down_rate", "verification_failure_rate", "citation_validity_rate"]
    : [];
  const latest = snapshot({
    diff: {
      deltas: drift
        ? { feedback_down_rate: 0.045, verification_failure_rate: 0.068, citation_validity_rate: -0.045 }
        : {},
      regressions,
      has_regressions: drift,
    },
    has_regressions: drift,
    metrics: {
      overall: { verification_failure_rate: drift ? 0.129 : 0.061, feedback_down_rate: drift ? 0.094 : 0.042 },
      regressed_models: drift ? ["claude-haiku-4.1"] : [],
    },
  });
  return {
    query_volume: 1942,
    avg_latency_ms: 4200,
    p95_latency_ms: 5800,
    total_cost_usd: 164.2,
    avg_cost_usd: 0.021,
    avg_confidence: 0.82,
    citation_validity_rate: drift ? 0.931 : 0.976,
    feedback_up: 900,
    feedback_down: drift ? 190 : 82,
    feedback_up_rate: 0.46,
    feedback_down_rate: drift ? 0.094 : 0.042,
    verification_failure_rate: drift ? 0.129 : 0.061,
    verification_breakdown: [
      { overall_status: "verified", count: 1800 },
      { overall_status: "needs_correction", count: 100 },
    ],
    by_model: [
      { model_used: "claude-haiku-4.5", query_volume: 1284, avg_latency_ms: 3900, avg_confidence: 0.81, avg_cost_usd: 0.019 },
      { model_used: "claude-sonnet-4.5", query_volume: 642, avg_latency_ms: 6700, avg_confidence: 0.86, avg_cost_usd: 0.058 },
      { model_used: "claude-haiku-4.1", query_volume: 148, avg_latency_ms: 3600, avg_confidence: drift ? 0.72 : 0.8, avg_cost_usd: 0.017 },
    ],
    by_day,
    latest_snapshot: latest,
    has_regressions: drift,
    snapshots: Array.from({ length: 8 }, (_, i) =>
      snapshot({
        id: `snap-${i}`,
        created_at: `2026-07-${String(13 + i).padStart(2, "0")}T06:00:00Z`,
        has_regressions: drift && i >= 6,
        metrics: { overall: { verification_failure_rate: 0.05 + i * 0.012 } },
      })
    ),
    ops_notifications: [],
  };
}

async function mockStats(page: Page, drift: boolean) {
  await page.route("**/api/admin/stats**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(buildStats({ drift })),
    });
  });
}

test.describe.configure({ mode: "serial" });

test("operator nav link routes to the analytics page", async ({ page }) => {
  await completeMagicLinkLogin(page, TEST_EMAIL);
  await mockStats(page, false);
  await page.goto("/dashboard/query");
  await page.getByRole("link", { name: /analytics/i }).click();
  await expect(page).toHaveURL(/\/dashboard\/analytics/, { timeout: 20_000 });
  await expect(page.getByRole("heading", { name: /pipeline analytics/i })).toBeVisible();
});

test("healthy state renders KPI cards and charts, no drift banner", async ({ page }) => {
  await completeMagicLinkLogin(page, TEST_EMAIL);
  await mockStats(page, false);
  await page.goto("/dashboard/analytics");

  await expect(page.getByRole("heading", { name: /pipeline analytics/i })).toBeVisible();
  // KPI cards render from the mocked response.
  await expect(page.getByText("Query volume").first()).toBeVisible();
  await expect(page.getByText("Citation-validity rate").first()).toBeVisible();
  await expect(page.locator('[data-slot="kpi-card"]').first()).toBeVisible({ timeout: 20_000 });
  // Trend charts render (recharts).
  await expect(page.locator('[data-slot="trend-chart"]').first()).toBeVisible();
  // Model breakdown table shows the concrete model ids.
  await expect(page.getByText("claude-haiku-4.5")).toBeVisible();
  // No drift banner in the healthy state.
  await expect(page.locator('[data-slot="drift-banner"]')).toHaveCount(0);
});

test("drift state shows the drift banner naming regressed metrics", async ({ page }) => {
  await completeMagicLinkLogin(page, TEST_EMAIL);
  await mockStats(page, true);
  await page.goto("/dashboard/analytics");

  const banner = page.locator('[data-slot="drift-banner"]');
  await expect(banner).toBeVisible({ timeout: 20_000 });
  await expect(banner.getByText(/model-performance drift detected/i)).toBeVisible();
  await expect(banner.getByText(/3 metrics regressed/i)).toBeVisible();
  // The regressed metrics are named in the banner.
  await expect(banner.getByText(/feedback-down rate/i)).toBeVisible();
  await expect(banner.getByText(/verification-failure rate/i)).toBeVisible();
  // The offending model row is flagged.
  await expect(page.locator('[data-slot="model-table"] tr[data-flagged]')).toHaveCount(1);
});
