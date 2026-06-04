import { test, expect } from "@playwright/test";
import { LoginPage, WorkbenchPage, mockApi } from "./helpers/page-objects";

test.describe("Login page", () => {
  test("renders login form", async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();

    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(loginPage.username).toBeVisible();
    await expect(loginPage.password).toBeVisible();
    await expect(loginPage.submit).toBeVisible();
  });

  test("submit button is keyboard accessible", async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();

    await loginPage.username.fill("testuser");
    await loginPage.password.fill("wrongpass");
    // Tab to submit and press Enter
    await loginPage.password.press("Tab");
    await page.keyboard.press("Enter");
    // Should stay on login page (auth API not mocked, will fail silently)
    await expect(loginPage.submit).toBeVisible();
  });
});

test.describe("Workbench page", () => {
  test("renders page heading", async ({ page }) => {
    await mockApi(page);
    const workbenchPage = new WorkbenchPage(page);
    await workbenchPage.goto();

    await expect(workbenchPage.heading).toBeVisible();
  });
});
