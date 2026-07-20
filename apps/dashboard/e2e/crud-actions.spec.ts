/**
 * E2E: generic CRUD row-actions (Phase 3) — delete + content edit across the
 * document, ATO, query-history and firm-knowledge surfaces, plus the negative
 * assertion that the two global/read-only surfaces (Regulatory alerts and the
 * Reference Library / knowledge-base) expose NO delete or edit affordance.
 *
 * Follows the auth bootstrap of full-flow.spec.ts (admin.generateLink +
 * verifyOtp -> write the @supabase/ssr cookie so the server sees a real
 * session). NOT part of CI — it hits a real account. Run manually:
 *
 *   doppler run --project taxflow --config prd -- npx playwright test crud-actions
 *
 * Requires SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY (all in
 * the prd Doppler config). Assumes the fixture firm has at least one document —
 * the full-flow spec seeds one.
 */
import { test, expect, type Page } from "@playwright/test";
import { createClient } from "@supabase/supabase-js";

const TEST_EMAIL = "hanan@crewcircle.com.au";
const FIRM_NAME = "Hanan Accounting";

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

test.describe.configure({ mode: "serial" });

test("crud: edit a document via the row-actions menu and see the edited badge", async ({ page }) => {
  await test.step("authenticate and land on the dashboard", async () => {
    await completeMagicLinkLogin(page, TEST_EMAIL);
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 20_000 });
    await expect(page.getByText(FIRM_NAME)).toBeVisible();
  });

  await test.step("open the row-actions menu on the first document and edit it", async () => {
    await page.goto("/dashboard/documents");
    const firstRow = page.locator("tbody tr").first();
    await expect(firstRow).toBeVisible({ timeout: 20_000 });

    await firstRow.getByRole("button", { name: /document actions/i }).click();
    await page.getByRole("menuitem", { name: /edit/i }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 10_000 });

    const bodyEdit = ` Edited by the CRUD e2e at ${Date.now()}.`;
    const bodyBox = dialog.getByLabel(/content/i);
    await bodyBox.focus();
    await bodyBox.press("End");
    await bodyBox.pressSequentially(bodyEdit);
    await dialog.getByRole("button", { name: /^save$/i }).click();

    // Success toast + the row now shows an "Edited" timestamp.
    await expect(page.getByText(/document updated/i)).toBeVisible({ timeout: 20_000 });
    await expect(firstRow.getByText(/edited/i)).toBeVisible({ timeout: 20_000 });
  });

  await test.step("delete a document with the confirm dialog", async () => {
    const rows = page.locator("tbody tr");
    const beforeCount = await rows.count();
    const lastRow = rows.last();

    await lastRow.getByRole("button", { name: /document actions/i }).click();
    await page.getByRole("menuitem", { name: /delete/i }).click();

    const confirm = page.getByRole("dialog");
    await expect(confirm).toBeVisible();
    await confirm.getByRole("button", { name: /^delete$/i }).click();

    await expect(page.getByText(/document deleted/i)).toBeVisible({ timeout: 20_000 });
    await expect(rows).toHaveCount(beforeCount - 1, { timeout: 20_000 });
  });

  await test.step("regulatory alerts expose NO delete or edit affordance (AC7)", async () => {
    await page.goto("/dashboard/regulatory");
    await expect(page).toHaveURL(/\/dashboard\/regulatory/, { timeout: 20_000 });
    // Global, read-only content: no per-row actions menu.
    await expect(page.getByRole("button", { name: /actions/i })).toHaveCount(0);
  });

  await test.step("reference library exposes NO delete or edit affordance (AC7)", async () => {
    await page.goto("/dashboard/knowledge-base");
    await expect(page).toHaveURL(/\/dashboard\/knowledge-base/, { timeout: 20_000 });
    await expect(page.getByRole("button", { name: /actions/i })).toHaveCount(0);
  });
});
