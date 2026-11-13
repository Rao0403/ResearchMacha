import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { installApiFixtures } from "./fixtures/api";

test.beforeEach(async ({ page }) => {
  await installApiFixtures(page);
});

test("renders the empty primary workspaces", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /ask one research question/i })).toBeVisible();

  await page.goto("/reader");
  await expect(page.getByText(/upload a pdf or open a saved paper id/i)).toBeVisible();

  await page.goto("/batch-summary");
  await expect(page.getByText(/no comparison loaded/i)).toBeVisible();
});

test("renders deterministic populated paper states", async ({ page }) => {
  await page.goto("/debug/library");

  await expect(page.getByRole("heading", { name: "Your paper collection" })).toBeVisible();
  for (const state of ["ready", "processing", "degraded", "failed"]) {
    await expect(page.getByText(`Fixture paper: ${state}`)).toBeVisible();
  }
});

test("uploads a saved comparison and reopens it without another generation", async ({ page }) => {
  const mutations: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/api/comparisons")) mutations.push(request.url());
  });
  await page.goto("/comparisons");
  await page.getByLabel("PDF collection").setInputFiles([
    { name: "first.pdf", mimeType: "application/pdf", buffer: Buffer.from("fixture PDF") },
    { name: "second.pdf", mimeType: "application/pdf", buffer: Buffer.from("fixture PDF") },
  ]);
  await page.getByRole("button", { name: "Upload and compare" }).click();
  await expect(page).toHaveURL(/\/comparisons\/saved-comparison$/);
  await expect(page.getByRole("table", { name: "Paper comparison matrix" })).toBeVisible();
  await page.reload();
  await expect(page.getByText("The studies report complementary evidence.")).toBeVisible();
  expect(mutations).toHaveLength(1);
  expect(mutations[0]).toContain("/api/comparisons/upload");
});

test("renders a deterministic blocked workflow", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Research question").fill(blockedProjectQuestion);
  await page.getByRole("button", { name: "Start research" }).click();

  await expect(page.getByRole("heading", { name: /resolve failed work before synthesis/i })).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Exclude" })).toBeVisible();
});

test("follows comparison evidence and saves a personal note that survives reopening", async ({ page }) => {
  await page.goto("/comparisons/saved-comparison");
  await page.getByRole("link",{name:"Open Fixture paper: ready, page 1: Measured improvement on the fixed benchmark."}).click();
  await expect(page).toHaveURL(/\/reader\/paper-ready\?page=1$/);
  await expect(page.getByRole("heading",{name:"Selected source passage"})).toBeVisible();
  // The first reader visit loads PDF.js and its worker while other browser tests run.
  await expect(page.locator(".pdf-canvas-shell canvas")).toBeVisible({timeout:15000});
  await page.getByRole("tab",{name:"My Notes",exact:true}).click();
  await page.getByLabel("Your note").fill("My portfolio evidence note");
  await page.getByRole("button",{name:"Use selected source passage"}).click();
  await page.getByRole("button",{name:"Save note",exact:true}).click();
  await expect(page.getByText("Note saved to your workspace.")).toBeVisible();
  await page.reload();
  await page.getByRole("tab",{name:"My Notes",exact:true}).click();
  await expect(page.getByText("My portfolio evidence note",{exact:true})).toBeVisible();
  await expect(page.getByRole("link",{name:"Back to evidence"})).toHaveAttribute("href","/comparisons/saved-comparison");
  const results=await new AxeBuilder({page}).analyze();
  expect(results.violations.filter((v) => ["serious","critical"].includes(v.impact ?? ""))).toEqual([]);
});

test("has no serious automated accessibility violations on primary workspaces", async ({ page }) => {
  for (const path of ["/", "/reader", "/batch-summary", "/library"]) {
    await page.goto(path);
    const results = await new AxeBuilder({ page }).analyze();
    const serious = results.violations.filter((violation) => ["serious", "critical"].includes(violation.impact ?? ""));
    expect(serious, `${path}: ${serious.map((violation) => violation.id).join(", ")}`).toEqual([]);
  }
});

test("keeps primary workspaces inside the viewport", async ({ page }) => {
  for (const path of ["/", "/reader", "/batch-summary", "/library"]) {
    await page.goto(path);
    const dimensions = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }));
    expect(dimensions.scrollWidth, `${path} overflows by ${dimensions.scrollWidth - dimensions.clientWidth}px`)
      .toBeLessThanOrEqual(dimensions.clientWidth + 1);
  }
});

test("supports keyboard skip navigation", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  const skipLink = page.getByRole("link", { name: "Skip to workspace" });
  await expect(skipLink).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();
});

test("respects reduced motion preferences", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const transitionDurationMs = await page.getByRole("button", { name: "Start research" })
    .evaluate((element) => {
      const value = getComputedStyle(element).transitionDuration;
      return value.endsWith("ms") ? Number.parseFloat(value) : Number.parseFloat(value) * 1000;
    });
  expect(transitionDurationMs).toBeLessThanOrEqual(0.01);
});

const blockedProjectQuestion = "How should domain evidence be evaluated?";
