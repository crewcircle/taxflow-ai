/**
 * E2E: in-app document viewer + annotations (Phase 1).
 *
 * Follows the auth bootstrap of full-flow.spec.ts (admin.generateLink +
 * verifyOtp -> write the @supabase/ssr cookie so the server sees a real
 * session). NOT part of CI — it hits a real account. Run manually:
 *
 *   doppler run --project taxflow --config prd -- npx playwright test annotations
 *
 * Requires SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY (all in
 * the prd Doppler config). Assumes the fixture firm has at least one document —
 * the full-flow spec seeds one; this spec opens the first document, renders its
 * content in-app, adds a comment on a selected span, reloads, and asserts the
 * highlight + gutter thread persist, then resolves and deletes it.
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

test("annotations: view a document in-app and add/resolve/delete a comment", async ({ page }) => {
  await test.step("authenticate and land on the dashboard", async () => {
    await completeMagicLinkLogin(page, TEST_EMAIL);
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 20_000 });
    await expect(page.getByText(FIRM_NAME)).toBeVisible();
  });

  await test.step("open the first document in the in-app viewer", async () => {
    await page.goto("/dashboard/documents");
    const viewLink = page.getByRole("link", { name: /^view$/i }).first();
    await expect(viewLink).toBeVisible({ timeout: 20_000 });
    await viewLink.click();
    await expect(page).toHaveURL(/\/dashboard\/documents\/[0-9a-f-]+/, { timeout: 20_000 });
    // content_md renders in-app (the annotatable article), not a download prompt.
    await expect(page.getByTestId("annotatable-article")).toBeVisible();
    await expect(page.getByTestId("annotation-gutter")).toBeVisible();
  });

  await test.step("select text and add a comment", async () => {
    const article = page.getByTestId("annotatable-article");
    // Select the first paragraph's text to open the composer dialog.
    const firstParagraph = article.locator("p").first();
    await firstParagraph.evaluate((el) => {
      const range = document.createRange();
      range.selectNodeContents(el);
      const sel = window.getSelection();
      sel?.removeAllRanges();
      sel?.addRange(range);
    });
    await firstParagraph.dispatchEvent("mouseup");

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 10_000 });
    await dialog.getByRole("button", { name: /comment/i }).click();
    await dialog.getByRole("textbox").fill("E2E test comment — please verify this figure.");
    await dialog.getByRole("button", { name: /add comment/i }).click();

    // Gutter thread appears.
    await expect(
      page.getByText("E2E test comment — please verify this figure.")
    ).toBeVisible({ timeout: 20_000 });
  });

  await test.step("comment persists across reload as a gutter thread", async () => {
    await page.reload();
    await expect(
      page.getByText("E2E test comment — please verify this figure.")
    ).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("annotation-thread").first()).toBeVisible();
  });

  await test.step("resolve then delete the comment", async () => {
    const thread = page.getByTestId("annotation-thread").first();
    await thread.getByRole("button", { name: /resolve/i }).click();
    // Deleting removes the thread from the gutter.
    await page.reload();
    const openThread = page.getByTestId("annotation-thread").first();
    // Switch to the Resolved filter to find it, then delete.
    await page.getByRole("button", { name: /^resolved/i }).click();
    await expect(
      page.getByText("E2E test comment — please verify this figure.")
    ).toBeVisible({ timeout: 20_000 });
    await openThread.getByRole("button").last().click(); // trash icon
    await expect(
      page.getByText("E2E test comment — please verify this figure.")
    ).toBeHidden({ timeout: 20_000 });
  });
});
