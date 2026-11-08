import { test, expect, type BrowserContext } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

const origin = process.env.APP_ORIGIN ?? "https://localhost:3443";
const accounts = JSON.parse(fs.readFileSync(path.resolve("../runtime/demo-accounts.local.json"), "utf8")).accounts;
const shopId = "00000000-0000-4000-8000-000000000001";
async function login(context: BrowserContext, account: any) {
  const response = await context.request.post(origin + "/api/v1/auth/login", {
    headers: { Origin: origin }, data: { identifier: account.phone, password: account.password },
  });
  expect(response.status(), await response.text()).toBe(200);
  return response.json();
}
async function call(context: BrowserContext, session: any, method: string, url: string, data?: any) {
  const response = await context.request.fetch(origin + "/api/v1" + url, { method,
    headers: { Origin: origin, "X-CSRF-Token": session.csrfToken, "Idempotency-Key": crypto.randomUUID() }, data });
  expect(response.status(), await response.text()).toBe(200);
  return response.json();
}

test("customer request reaches only its shop, then opens and notifies in real time", async ({ browser }) => {
  if (!process.env.AUDIT_EVIDENCE_DIR) throw new Error("Run with isolated_validation.py");
  const ac = await browser.newContext({ ignoreHTTPSErrors: true });
  const cc = await browser.newContext({ ignoreHTTPSErrors: true });
  const sc = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const admin = await login(ac, accounts[0]);
    const credentials = { phone: "+849" + crypto.randomInt(10000000, 99999999), password: "RequestBrowser123!" };
    await call(ac, admin, "POST", "/admin/staff", { ...credentials, name: "Request seller browser", role: "SELLER" });
    await login(sc, credentials); await login(cc, accounts[2]);
    const template = (await call(ac, admin, "GET", "/admin/products"))[0];
    const name = "Sản phẩm yêu cầu " + crypto.randomUUID().slice(0, 8);
    const product = await call(ac, admin, "POST", "/admin/products", {
      name, categoryId: template.category_id, unitId: template.unit_id, quantityStep: "1", defaultCostPrice: "20000",
    });
    const cp = await cc.newPage(), sp = await sc.newPage();
    const errors: string[] = []; cp.on("pageerror", e => errors.push(e.message)); sp.on("pageerror", e => errors.push(e.message));
    await cp.goto("/product-requests"); await sp.goto("/shop/product-requests");
    await expect(cp.getByText("Đang đồng bộ", { exact: true })).toBeVisible();
    await expect(sp.getByText("Đang đồng bộ", { exact: true })).toBeVisible();
    await cp.getByRole("button", { name: "Gửi yêu cầu sản phẩm", exact: true }).click();
    const form = cp.getByRole("region", { name: "Yêu cầu sản phẩm mới" });
    await form.getByLabel("Shop tiếp nhận").selectOption(shopId);
    await form.getByLabel("Tên sản phẩm", { exact: true }).fill(name);
    await form.getByLabel("Mô tả mong muốn").fill("Hộp nhỏ, không đường, dùng cho bữa sáng");
    await form.getByLabel("Số lượng mong muốn").fill("2");
    await form.getByLabel("Đơn vị", { exact: true }).fill("hộp");
    await form.getByRole("button", { name: "Gửi tới shop" }).click();
    await expect(form).toHaveCount(0);
    await expect(cp.getByRole("region", { name: "Chi tiết yêu cầu sản phẩm" })).toContainText(name);
    await sp.locator(".request-row").filter({ hasText: name }).click();
    const detail = sp.getByRole("region", { name: "Chi tiết yêu cầu sản phẩm" });
    await detail.getByRole("button", { name: "Tiếp nhận xem xét" }).click();
    await detail.getByLabel("Sản phẩm liên kết").selectOption(product.id);
    await detail.getByRole("button", { name: "Xác nhận chờ mở bán" }).click();
    await expect(detail.locator(".row-heading .status")).toHaveText("Chờ mở bán");
    const vnDay = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Ho_Chi_Minh" });
    await call(ac, admin, "POST", "/admin/menus", { saleDate: vnDay, status: "OPEN",
      opensAt: new Date(Date.now() - 1000).toISOString(), closesAt: new Date(Date.now() + 3600000).toISOString(),
      items: [{ productId: product.id, availableQty: "10", costPrice: "20000" }] });
    await expect(detail.locator(".row-heading .status")).toHaveText("Đã mở bán");
    const customerDetail = cp.getByRole("region", { name: "Chi tiết yêu cầu sản phẩm" });
    await expect(customerDetail.getByRole("button", { name: "Xem hàng của shop" })).toBeVisible();
    await expect(customerDetail.getByRole("button", { name: "Hủy yêu cầu" })).toHaveCount(0);
    await cp.screenshot({ path: path.join(process.env.AUDIT_EVIDENCE_DIR, "product-request-customer.png"), fullPage: true });
    await sp.screenshot({ path: path.join(process.env.AUDIT_EVIDENCE_DIR, "product-request-seller.png"), fullPage: true });
    expect(errors).toEqual([]);
  } finally { await Promise.all([ac.close(), cc.close(), sc.close()]); }
});

test("requests support mobile width, keyboard and reload routes", async ({ page, context }) => {
  await login(context, accounts[1]);
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/product-requests");
  await expect(page.getByRole("heading", { name: "Yêu cầu sản phẩm", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Gửi yêu cầu sản phẩm", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Gửi yêu cầu sản phẩm", exact: true }).click();
  await page.getByLabel("Tên sản phẩm", { exact: true }).focus();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Mô tả mong muốn")).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  if (process.env.AUDIT_EVIDENCE_DIR) await page.screenshot({ path: path.join(process.env.AUDIT_EVIDENCE_DIR, "product-request-mobile.png"), fullPage: true });
  await page.reload();
  await expect(page).toHaveURL(origin + "/product-requests");
  await expect(page.getByRole("heading", { name: "Yêu cầu sản phẩm", exact: true })).toBeVisible();
});
