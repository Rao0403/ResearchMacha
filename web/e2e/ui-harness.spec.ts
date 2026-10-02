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
  await expect(page.getByText(/no batch loaded yet/i)).toBeVisible();
});

test("renders deterministic populated paper states", async ({ page }) => {
  await page.goto("/debug/library");

  await expect(page.getByRole("heading", { name: "Saved papers" })).toBeVisible();
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

test("has no critical automated accessibility violations on primary empty screens", async ({ page }) => {
  for (const path of ["/", "/reader", "/batch-summary"]) {
    await page.goto(path);
    const results = await new AxeBuilder({ page }).analyze();
    const critical = results.violations.filter((violation) => violation.impact === "critical");
    expect(critical, `${path}: ${critical.map((violation) => violation.id).join(", ")}`).toEqual([]);
  }
});

const blockedProjectQuestion = "How should domain evidence be evaluated?";
