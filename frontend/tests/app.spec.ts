import { test, expect, BrowserContext, Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

const origin = process.env.APP_ORIGIN ?? "https://localhost:3443";
const data = JSON.parse(
  fs.readFileSync(path.resolve("../runtime/demo-accounts.local.json"), "utf8"),
);
const evidence =
  process.env.AUDIT_EVIDENCE_DIR ??
  path.resolve("../runtime/browser-test-results");
const day = () =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Ho_Chi_Minh",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
let product: any, offer: any, menu: any;

async function login(context: BrowserContext, index: number) {
  const a = data.accounts[index];
  const response = await context.request.post(origin + "/api/v1/auth/login", {
    headers: { Origin: origin },
    data: { identifier: a.phone, password: a.password },
  });
  expect(response.status()).toBe(200);
  return await response.json();
}
async function call(
  context: BrowserContext,
  session: any,
  method: string,
  url: string,
  body?: any,
) {
  const r = await context.request.fetch(origin + "/api/v1" + url, {
    method,
    headers: {
      Origin: origin,
      "X-CSRF-Token": session.csrfToken,
      "Idempotency-Key": crypto.randomUUID(),
    },
    data: body,
  });
  expect(r.status(), await r.text()).toBe(200);
  return await r.json();
}
async function shot(page: Page, name: string) {
  fs.mkdirSync(path.join(evidence, "screenshots"), { recursive: true });
  await page.screenshot({
    path: path.join(evidence, "screenshots", name + ".png"),
    fullPage: false,
  });
}

test.beforeAll(async ({ browser }) => {
  if (!process.env.AUDIT_EVIDENCE_DIR)
    throw new Error("Browser acceptance must use isolated_validation.py");
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const a = await login(context, 0);
  const products = await call(context, a, "GET", "/admin/products");
  const p = products[0];
  product = await call(context, a, "POST", "/admin/products", {
    name: "Món kiểm thử giao diện " + crypto.randomUUID().slice(0, 6),
    categoryId: p.category_id,
    unitId: p.unit_id,
    quantityStep: "1",
    defaultCostPrice: "12000",
    defaultSalePrice: "30000",
  });
  const list = await call(context, a, "GET", "/admin/menus");
  menu = list.find((m: any) => m.sale_date === day());
  const full = menu
    ? await call(context, a, "GET", "/admin/menus/" + menu.id)
    : null;
  const items = (full?.items ?? []).map((i: any) => ({
    productId: i.product_id,
    availableQty: i.available_qty,
    costPrice: i.cost_price,
    enabled: i.status === "OPEN",
    expectedVersion: i.version,
    prices: i.prices.map((p: any) => ({
      groupId: p.group_id,
      unitPrice: p.unit_price,
    })),
  }));
  items.push({
    productId: product.id,
    availableQty: "20",
    costPrice: "12000",
    enabled: true,
    prices: Object.values(data.groups).map((g) => ({
      groupId: g,
      unitPrice: "30000",
    })),
  });
  menu = await call(
    context,
    a,
    full ? "PATCH" : "POST",
    "/admin/menus" + (full ? "/" + full.id : ""),
    {
      saleDate: day(),
      status: "OPEN",
      expectedVersion: full?.version,
      items,
      allowedGroupIds: null,
    },
  );
  offer = menu.items.find((i: any) => i.product_id === product.id);
  await context.close();
});

test("customer cart opens on add, merges, closes and restores focus", async ({
  context,
  page,
}) => {
  await login(context, 1);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Menu hôm nay" }),
  ).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const item = page.locator(`[data-offer-id="${offer.id}"]`);
  const add = item.getByRole("button", { name: "Thêm 1" });
  await add.click();
  await expect(page.getByRole("dialog", { name: "Giỏ hàng" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(add).toBeFocused();
  await add.click();
  await expect(page.locator(".quantity-controls")).toContainText("2");
  await shot(page, "daily-cart-desktop");
  await page.getByRole("button", { name: "Mua tiếp" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("collective checkout, direct admin actions, real WebSocket stock updates", async ({
  browser,
}) => {
  const customer = await browser.newContext({ ignoreHTTPSErrors: true });
  const admin = await browser.newContext({ ignoreHTTPSErrors: true });
  const c = await login(customer, 1);
  await login(admin, 0);
  const cp = await customer.newPage(),
    ap = await admin.newPage();
  await cp.goto("/");
  await ap.goto("/");
  await cp
    .locator(`[data-offer-id="${offer.id}"]`)
    .getByRole("button", { name: "Thêm 1" })
    .click();
  await cp.getByRole("button", { name: "Tiếp tục đặt hàng" }).click();
  const options = await call(customer, c, "GET", "/delivery/options");
  const address = (await call(customer, c, "GET", "/me/addresses"))[0];
  const policy = options.policies.find(
    (p: any) => p.zone_id === address.zone_id && p.method === "COLLECTIVE",
  );
  await cp.getByLabel("Cách nhận hàng").selectOption(policy.id);
  await cp.getByLabel("Tôi đã kiểm tra").check();
  await cp.getByRole("button", { name: "Đặt hàng · Chờ duyệt" }).click();
  await expect(cp.getByRole("heading", { name: "Đơn của tôi" })).toBeVisible();
  const row = ap.locator("tbody tr").filter({ hasText: product.name }).first();
  await expect(
    row.getByRole("button", { name: "Duyệt", exact: true }),
  ).toBeVisible();
  await row.getByRole("button", { name: "Duyệt", exact: true }).click();
  await expect(
    row.getByRole("button", { name: "Chuẩn bị", exact: true }),
  ).toBeVisible();
  await expect(ap.getByRole("dialog")).toHaveCount(0);
  for (const button of ["Chuẩn bị", "Bàn giao", "Đã giao"])
    await row.getByRole("button", { name: button, exact: true }).click();
  await expect(
    cp.locator("tbody tr").filter({ hasText: product.name }).first(),
  ).toContainText("Đã giao");
  await shot(ap, "direct-order-actions");
  await customer.close();
  await admin.close();
});

test("mobile navigation, Vietnamese address picker, reconnect and cart layout", async ({
  context,
  page,
}) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await login(context, 1);
  await page.goto("/");
  await expect(page.locator("aside.nav")).toBeHidden();
  await page.getByRole("button", { name: "Đóng mở thanh điều hướng" }).click();
  await expect(page.locator("aside.nav")).toBeVisible();
  await page
    .getByRole("button", { name: "Hồ sơ & địa chỉ", exact: true })
    .click();
  const first = page.locator(".list-row").first();
  await first.getByRole("button", { name: "Sửa", exact: true }).click();
  await expect(page.getByLabel("Tìm và xác nhận vị trí")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Đóng mở thanh điều hướng" }).click();
  await page
    .getByRole("button", { name: "Hàng trong ngày", exact: true })
    .click();
  await page
    .locator(`[data-offer-id="${offer.id}"]`)
    .getByRole("button", { name: "Thêm 1" })
    .click();
  await expect(page.getByRole("dialog", { name: "Giỏ hàng" })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await shot(page, "daily-cart-mobile");
  await page.keyboard.press("Escape");
  await context.setOffline(true);
  await expect(
    page.getByText("Đang khôi phục kết nối.", { exact: false }),
  ).toBeVisible();
  await context.setOffline(false);
  await expect(page.locator(".connection")).toContainText("Đang đồng bộ", {
    timeout: 30000,
  });
  await page
    .locator(`[data-offer-id="${offer.id}"]`)
    .getByRole("button", { name: "Thêm 1" })
    .click();
  await expect(page.locator(".quantity-controls")).toContainText("2");
});

test("admin menu editor, sidebar collapse, gross profit report and retired navigation", async ({
  context,
  page,
}) => {
  await login(context, 0);
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Yêu cầu hàng", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Đóng mở thanh điều hướng" }).click();
  await expect(page.locator(".shell")).toHaveClass(/nav-collapsed/);
  await page
    .getByRole("button", { name: "Menu theo ngày", exact: true })
    .click();
  const row = page.locator("tbody tr").filter({ hasText: day() }).first();
  await row.getByRole("button", { name: "Sửa món / giá / kho" }).click();
  await expect(page.locator(".menu-editor")).toBeVisible();
  await expect(page.getByText(product.name, { exact: true })).toBeVisible();
  await shot(page, "daily-menu-admin");
  await page.getByRole("button", { name: "Báo cáo", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Doanh thu và lãi gộp" }),
  ).toBeVisible();
  await expect(
    page.getByText("Lãi gộp", { exact: true }).first(),
  ).toBeVisible();
  await shot(page, "daily-profit-report");
});

test("chat text and image delivered to customer over real server", async ({
  browser,
}) => {
  const ca = await browser.newContext({ ignoreHTTPSErrors: true }),
    cb = await browser.newContext({ ignoreHTTPSErrors: true });
  const a = await login(ca, 0),
    b = await login(cb, 1);
  const ap = await ca.newPage(),
    bp = await cb.newPage();
  await ap.goto("/");
  await bp.goto("/");
  await bp.getByRole("button", { name: "Nhắn người bán", exact: true }).click();
  const convo = await call(cb, b, "GET", "/conversations/me");
  const text = "Kiểm tra tin nhắn mới " + crypto.randomUUID();
  await call(ca, a, "POST", "/conversations/" + convo.id + "/messages", {
    clientMessageId: crypto.randomUUID(),
    text,
  });
  await expect(bp.locator(".message").filter({ hasText: text })).toBeVisible();
  const upload = await ca.request.post(origin + "/api/v1/media", {
    headers: { Origin: origin, "X-CSRF-Token": a.csrfToken },
    multipart: {
      purpose: "CHAT",
      file: {
        name: "test.png",
        mimeType: "image/png",
        buffer: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aHc8AAAAASUVORK5CYII=",
          "base64",
        ),
      },
    },
  });
  expect(upload.status()).toBe(200);
  const asset = await upload.json();
  await call(ca, a, "POST", "/conversations/" + convo.id + "/messages", {
    clientMessageId: crypto.randomUUID(),
    text: "Ảnh kiểm thử",
    assetIds: [asset.id],
  });
  await expect(bp.locator(".message img").last()).toBeVisible();
  await shot(bp, "daily-chat");
  await ca.close();
  await cb.close();
});
test("price change keeps old cart until explicit customer confirmation", async ({
  browser,
}) => {
  const customer = await browser.newContext({ ignoreHTTPSErrors: true }),
    admin = await browser.newContext({ ignoreHTTPSErrors: true });
  await login(customer, 1);
  const a = await login(admin, 0);
  const page = await customer.newPage();
  await page.goto("/");
  await page
    .locator(`[data-offer-id="${offer.id}"]`)
    .getByRole("button", { name: "Thêm 1" })
    .click();
  const current = await call(admin, a, "GET", "/admin/menus/" + menu.id);
  const items = current.items.map((i: any) => ({
    productId: i.product_id,
    availableQty: i.available_qty,
    costPrice: i.cost_price,
    enabled: i.status === "OPEN",
    expectedVersion: i.version,
    prices: i.prices.map((p: any) => ({
      groupId: p.group_id,
      unitPrice: i.id === offer.id ? "31000" : p.unit_price,
    })),
  }));
  await call(admin, a, "PATCH", "/admin/menus/" + menu.id, {
    expectedVersion: current.version,
    items,
    status: "OPEN",
  });
  await expect(
    page.getByText("Giá hoặc lượng còn đã đổi.", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Tiếp tục đặt hàng" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Cập nhật giỏ hàng" }).click();
  await expect(page.getByRole("dialog")).toContainText("31.000");
  await expect(
    page.getByRole("button", { name: "Tiếp tục đặt hàng" }),
  ).toBeEnabled();
  await customer.close();
  await admin.close();
});
