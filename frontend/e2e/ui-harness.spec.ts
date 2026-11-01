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

test("renders a deterministic blocked workflow", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Research question").fill(blockedProjectQuestion);
  await page.getByRole("button", { name: "Start research" }).click();

  await expect(page.getByRole("heading", { name: /resolve failed work before synthesis/i })).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Exclude" })).toBeVisible();
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
