import {test, expect} from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
const origin = process.env.APP_ORIGIN ?? "https://localhost:3443";
const account = JSON.parse(fs.readFileSync(path.resolve("../runtime/demo-accounts.local.json"), "utf8")).accounts[1];
test.use({ignoreHTTPSErrors: new URL(origin).hostname === "localhost"});
for (const reduced of [false, true]) {
  test(`motion ${reduced ? "reduced" : "enabled"}: cart and layout remain usable`, async ({page, context}) => {
    await page.emulateMedia({reducedMotion: reduced ? "reduce" : "no-preference"});
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.name));
    const response = await context.request.post(origin + "/api/v1/auth/login", {
      headers: {Origin: origin}, data: {identifier: account.phone, password: account.password},
    });
    expect(response.status()).toBe(200);
    const session = await response.json();
    try {
      await page.setViewportSize({width: 1440, height: 960});
      await page.goto(origin + "/menu");
      await expect(page.getByText("Đang đồng bộ", {exact: true})).toBeVisible();
      const card = page.locator(".daily-products .daily-product").first();
      await expect(card).toBeVisible();
      expect(await card.evaluate(el => getComputedStyle(el).animationName)).toBe(reduced ? "none" : "enter-soft");
      await card.getByRole("button", {name: "Thêm vào giỏ", exact: true}).click();
      const modal = page.locator(".cart-drawer .modal");
      await expect(modal).toBeVisible();
      expect(await modal.evaluate(el => getComputedStyle(el).animationName)).toBe(reduced ? "none" : "drawer-in");
      await page.waitForTimeout(300);
      const desktop = await modal.boundingBox();
      expect(desktop!.x + desktop!.width).toBeLessThanOrEqual(1441);
      await modal.locator(".modal-head button").click();
      await page.getByRole("link", {name: "Hồ sơ & địa chỉ", exact: true}).click();
      await expect(page).toHaveURL(origin + "/profile");
      await page.goBack();
      await expect(page).toHaveURL(origin + "/menu");
      await page.setViewportSize({width: 360, height: 820});
      await page.locator(".daily-products .daily-product").first().getByRole("button", {name: "Thêm vào giỏ", exact: true}).click();
      await expect(modal).toBeVisible();
      await page.waitForTimeout(300);
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false);
      if (reduced) expect(await page.evaluate(() => document.getAnimations().filter(a => a.playState === "running").length)).toBe(0);
      await page.screenshot({path: `../runtime/browser-test-results/motion-${reduced ? "reduced" : "enabled"}-mobile.png`});
      expect(errors).toEqual([]);
    } finally {
      await context.request.post(origin + "/api/v1/auth/logout", {headers: {Origin: origin, "X-CSRF-Token": session.csrfToken}});
    }
  });
}
