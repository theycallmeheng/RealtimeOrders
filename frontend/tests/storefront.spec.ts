import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const origin = process.env.APP_ORIGIN ?? "https://localhost:3443";
const account = JSON.parse(fs.readFileSync(path.resolve("../runtime/demo-accounts.local.json"), "utf8")).accounts[1];

test("storefront keeps keyboard navigation, four columns and docked cart within the screen", async ({ page, context }) => {
  if (!process.env.AUDIT_EVIDENCE_DIR) throw new Error("Use isolated_validation.py for browser acceptance");
  const login = await context.request.post(origin + "/api/v1/auth/login", {
    headers: { Origin: origin }, data: { identifier: account.phone, password: account.password },
  });
  expect(login.status()).toBe(200);
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/menu");
  await expect(page.getByRole("heading", { name: "Menu hôm nay" })).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Đến nội dung chính" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();
  const grid = page.locator(".daily-products");
  await expect(grid.locator(".daily-product").first()).toBeVisible();
  expect(await grid.evaluate(el => getComputedStyle(el).gridTemplateColumns.split(" ").length)).toBe(4);
  await grid.locator(".daily-product").first().getByRole("button", { name: "Thêm vào giỏ", exact: true }).click();
  const cart = page.getByRole("complementary", { name: "Giỏ hàng" });
  await expect(cart).toBeVisible();
  await page.waitForTimeout(300);
  const header = await page.locator(".app-header").boundingBox();
  const box = await cart.boundingBox();
  expect(box!.y).toBeGreaterThanOrEqual(header!.y + header!.height - 1);
  expect(box!.x + box!.width).toBeLessThanOrEqual(1441);
  const columns = await grid.evaluate(el => getComputedStyle(el).gridTemplateColumns.split(" ").length);
  expect(columns).toBeGreaterThanOrEqual(2);
  expect(columns).toBeLessThanOrEqual(3);
  await cart.locator(".cart-quantity-input").first().focus();
  await page.keyboard.press("Escape");
  await expect(cart).not.toBeVisible();
  for (const width of [360, 768]) {
    await page.setViewportSize({ width, height: 820 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  }
  await page.setViewportSize({ width: 360, height: 820 });
  await page.getByRole("button", { name: "Đóng mở thanh điều hướng" }).click();
  await expect(page.getByRole("link", { name: "Bảng tin cửa hàng", exact: true })).toBeVisible();
  const nav = await page.locator("aside.nav").boundingBox();
  expect(nav!.y).toBe(64);
  await page.getByRole("link", { name: "Bảng tin cửa hàng", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Bảng tin cửa hàng" })).toBeVisible();
  await expect(page.locator("aside.nav")).not.toBeVisible();
});


test("customer can filter shops directly and restore all shops", async ({page,context}) => {
  if(!process.env.AUDIT_EVIDENCE_DIR) throw new Error("Use isolated_validation.py");
  const login=await context.request.post(origin+"/api/v1/auth/login",{headers:{Origin:origin},data:{identifier:account.phone,password:account.password}});
  expect(login.status()).toBe(200);
  await page.goto("/menu");
  const group=page.getByRole("group",{name:"Lọc theo shop",exact:true});
  const choices=group.getByRole("button");
  await expect(choices.first()).toHaveAttribute("aria-pressed","true");
  expect(await choices.count()).toBeGreaterThan(1);
  await choices.nth(1).click();
  await expect(choices.nth(1)).toHaveAttribute("aria-pressed","true");
  await expect(choices.first()).toHaveAttribute("aria-pressed","false");
  await page.reload();
  await expect(choices.nth(1)).toHaveAttribute("aria-pressed","true");
  await choices.first().click();
  await expect(choices.first()).toHaveAttribute("aria-pressed","true");
  await expect(page.locator(".daily-product").first()).toBeVisible();
  await page.setViewportSize({width:360,height:820});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
