/**
 * Full-flow E2E test: signup through every major feature, as a brand-new
 * real (non-demo) account - "Hanan Accounting", a small-business specialist
 * firm. This is the fourth persona/use case, distinct from the three seeded
 * demo personas, exercising the real signup + auth + trial path.
 *
 * NOT part of the CI pipeline (deliberately - it creates a real production
 * account and makes real Anthropic API calls). Run manually before a major
 * release:
 *
 *   doppler run --project taxflow --config prd -- npx playwright test
 *
 * Requires SUPABASE_URL, SUPABASE_ANON_KEY and SUPABASE_SERVICE_ROLE_KEY in
 * the environment (all present in the `prd` Doppler config) to complete
 * magic-link auth without a real inbox. Real signup/login uses PKCE (code
 * exchanged server-side via /auth/callback), which requires a code_verifier
 * only the original browser holds - the admin API can't replicate that for
 * an arbitrary email. Instead this mirrors the backend's own demo-login
 * mechanism (admin.generateLink + verifyOtp to get real session tokens
 * directly) and writes them into the exact cookie @supabase/ssr's browser
 * client uses, so the server sees a fully real, valid session. Everything
 * else in this test drives the real UI exactly as a user would.
 */
import { test, expect, type Page } from "@playwright/test";
import { createClient } from "@supabase/supabase-js";
import path from "node:path";

const TEST_EMAIL = "hanan@crewcircle.com.au";
const FIRM_NAME = "Hanan Accounting";
const QUESTION =
  "What is the instant asset write-off threshold for a small business this financial year?";

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

  // Write the session into the exact cookie format @supabase/ssr's browser
  // client reads (storage key `sb-<project-ref>-auth-token`, value prefixed
  // "base64-" and base64url-encoded) so the server sees a real session on
  // the very first request - no client-side redirect dance required.
  const projectRef = new URL(supabaseUrl).hostname.split(".")[0];
  const cookieValue = "base64-" + Buffer.from(JSON.stringify(otpData.session), "utf-8").toString("base64url");
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

test.describe.configure({ mode: "serial" });

test("full flow: signup, ask a question, documents, firm knowledge, ATO letter, settings, sign out", async ({
  page,
}) => {
  await test.step("sign up as a new firm", async () => {
    await page.goto("/signup");
    await page.fill("#business_name", FIRM_NAME);
    await page.fill("#email", TEST_EMAIL);
    await page.fill("#suburb", "Parramatta");
    // business_type and state keep their sensible defaults (accounting / NSW).
    await page.getByRole("button", { name: /start free trial/i }).click();
    // The account persists across runs (per the "keep the account" decision
    // for this fixture), so a re-run hits the "already exists" path - both
    // outcomes prove the signup endpoint behaves correctly.
    await expect(
      page.getByText(/your 30-day free trial is ready|account with this email already exists/i)
    ).toBeVisible({ timeout: 20_000 });
  });

  await test.step("complete magic-link auth and land on the dashboard", async () => {
    await completeMagicLinkLogin(page, TEST_EMAIL);
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/dashboard\/query/, { timeout: 20_000 });
    await expect(page.getByText(FIRM_NAME)).toBeVisible();
  });

  await test.step("ask a real question and get a sourced, verified answer", async () => {
    const textarea = page.getByPlaceholder(/ask an australian tax question/i);
    await expect(textarea).toBeVisible();
    await textarea.fill(QUESTION);
    await page.getByRole("button", { name: /ask taxflow/i }).click();

    // Real Claude round-trip: research -> stream -> verify. Generous timeout.
    await expect(page.locator("text=/./").first()).toBeVisible();
    await expect(page.getByText(/verifying/i)).toBeVisible({ timeout: 30_000 }).catch(() => {});
    await expect(
      page.getByText(/verified against sources|claim.*need review|note/i)
    ).toBeVisible({ timeout: 90_000 });
  });

  await test.step("save the answer as a document", async () => {
    await page.getByRole("button", { name: /^save as document$/i }).click();
    await expect(page.getByRole("link", { name: /view saved document/i })).toBeVisible({
      timeout: 20_000,
    });
  });

  await test.step("saved document appears on the Documents page", async () => {
    await page.goto("/dashboard/documents");
    await expect(page.getByText(QUESTION.slice(0, 40))).toBeVisible({ timeout: 20_000 });
  });

  await test.step("upload firm knowledge", async () => {
    await page.goto("/dashboard/knowledge");
    await page.setInputFiles('input[type="file"]', path.join(__dirname, "fixtures/firm-knowledge.txt"));
    await page.getByRole("button", { name: /upload document/i }).click();
    await expect(page.getByText("firm-knowledge.txt")).toBeVisible({ timeout: 20_000 });
  });

  await test.step("upload an ATO letter and get a classification + draft response", async () => {
    await page.goto("/dashboard/ato-response");
    await page.setInputFiles('input[type="file"]', path.join(__dirname, "fixtures/ato-letter.pdf"));
    await page.getByRole("button", { name: /upload and analyse/i }).click();
    await expect(page.getByText(/draft response/i)).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText(/download as \.docx/i)).toBeVisible();
  });

  await test.step("regulatory updates page loads", async () => {
    await page.goto("/dashboard/regulatory");
    await expect(page.getByRole("heading", { name: /regulatory updates/i })).toBeVisible();
    await expect(page.getByText(/could not load/i)).toHaveCount(0);
  });

  await test.step("update settings", async () => {
    await page.goto("/dashboard/settings");
    const phone = page.locator("#phone");
    await expect(phone).toBeVisible({ timeout: 20_000 });
    await phone.fill("0400 000 000");
    await page.getByRole("button", { name: /save changes/i }).click();
    await expect(page.getByText(/^saved$/i)).toBeVisible({ timeout: 10_000 });
  });

  await test.step("sign out", async () => {
    await page.getByRole("button", { name: /sign out/i }).click();
    await expect(page).toHaveURL(/\/login/, { timeout: 20_000 });
  });
});
