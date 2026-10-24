import { test, expect, Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
const data = JSON.parse(
  fs.readFileSync(path.resolve("../runtime/demo-accounts.local.json"), "utf8"),
);
const evidence = process.env.AUDIT_EVIDENCE_DIR
  ? path.resolve(process.env.AUDIT_EVIDENCE_DIR, "screenshots")
  : path.resolve("../evidence");
fs.mkdirSync(evidence, { recursive: true });
async function login(page: Page, index: number) {
  await page.goto("/");
  await page
    .getByLabel("Số điện thoại hoặc email")
    .fill(data.accounts[index].phone);
  await page
    .getByLabel("Mật khẩu", { exact: true })
    .fill(data.accounts[index].password);
  await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();
  await expect(page.getByText("Đang đồng bộ", { exact: true })).toBeVisible({
    timeout: 30000,
  });
}

test("customer creates an order, admin approves, realtime and image chat", async ({
  browser,
}) => {
  const a = await browser.newContext({ ignoreHTTPSErrors: true }),
    b = await browser.newContext({ ignoreHTTPSErrors: true });
  const customer = await a.newPage(),
    admin = await b.newPage();
  const errors: string[] = [];
  customer.on("pageerror", (e) => errors.push(e.message));
  admin.on("pageerror", (e) => errors.push(e.message));
  await login(customer, 1);
  await customer.screenshot({
    path: path.join(evidence, "customer-desktop.png"),
    fullPage: true,
  });
  const row = customer
    .locator("tr")
    .filter({ hasText: "Cam sành" })
    .filter({
      has: customer.getByRole("button", { name: "Thêm", exact: true }),
    })
    .first();
  await row.getByRole("button", { name: "Thêm", exact: true }).click();
  await expect(
    customer.getByText("Đơn đang soạn", { exact: true }),
  ).toBeVisible();
  // Choose free collective delivery for the student fixture.
  await customer
    .getByLabel("Cách giao", { exact: true })
    .selectOption({ label: "Giao tập trung · miễn phí" });
  await customer.getByRole("button", { name: "Gửi đơn chờ duyệt" }).click();
  await expect(
    customer.getByText("Đơn đã gửi và đang chờ người bán duyệt."),
  ).toBeVisible();
  await customer
    .getByRole("button", { name: "Đơn của tôi", exact: true })
    .click();
  const orderRow = customer.locator("tbody tr").first();
  const id = await orderRow.locator("td").first().locator("strong").innerText();
  await login(admin, 0);
  const target = admin.locator("tbody tr").filter({ hasText: id });
  await target.getByRole("button", { name: "Chi tiết" }).click();
  await admin.getByRole("button", { name: "Duyệt toàn bộ đơn" }).click();
  await expect(
    admin.getByRole("dialog").getByText("Đã duyệt", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    customer
      .locator("tbody tr")
      .filter({ hasText: id })
      .getByText("Đã duyệt", { exact: true }),
  ).toBeVisible({ timeout: 15000 });
  await admin.getByRole("button", { name: "Đóng", exact: true }).click();
  await admin.screenshot({
    path: path.join(evidence, "admin-orders.png"),
    fullPage: true,
  });
  await customer.getByRole("button", { name: "Nhắn người bán" }).click();
  const message='Chào người bán, đơn của tôi đã được duyệt. '+Date.now();
  await customer
    .getByRole("textbox", { name: "Nội dung tin nhắn" })
    .fill(message);
  await customer.getByRole("button", { name: "Gửi", exact: true }).click();
  await expect(
    customer
      .getByRole("log")
      .getByText(message),
  ).toBeVisible();
  await customer.getByLabel("Chọn ảnh gửi chat").setInputFiles({
    name: "test.png",
    mimeType: "image/png",
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWs0AAAAASUVORK5CYII=",
      "base64",
    ),
  });
  await expect(customer.getByText("1 ảnh đã tải")).toBeVisible();
  await customer.getByRole("button", { name: "Gửi", exact: true }).click();
  await expect(
    customer.getByAltText("Ảnh trong hội thoại").last(),
  ).toBeVisible();
  await customer.screenshot({
    path: path.join(evidence, "customer-chat.png"),
    fullPage: true,
  });
  expect(errors).toEqual([]);
  await a.close();
  await b.close();
});

test("mobile 360px, keyboard, profile and all admin screens", async ({
  browser,
}) => {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 360, height: 800 },
  });
  const page = await context.newPage();
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page, 2);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: path.join(evidence, "customer-mobile-360.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Hồ sơ & địa chỉ" }).click();
  await expect(
    page.getByRole("heading", { name: "Địa chỉ nhận hàng" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Thêm", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "Thông báo", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Thông báo", exact: true }),
  ).toBeVisible();
  await context.close();
  const admin = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1280, height: 900 },
  });
  const p = await admin.newPage();
  p.on("pageerror", (e) => errors.push(e.message));
  await login(p, 0);
  for (const label of [
    "Đợt mở bán",
    "Sản phẩm",
    "Yêu cầu hàng",
    "Tin nhắn",
    "Khách hàng",
    "Cấu hình",
    "Báo cáo",
    "Nhật ký",
  ]) {
    await p
      .locator("aside")
      .getByRole("button", { name: label, exact: true })
      .click();
    await expect(p.locator("main h1")).toBeVisible();
    await p.waitForTimeout(250);
  }
  await p.screenshot({
    path: path.join(evidence, "admin-audit.png"),
    fullPage: true,
  });
  expect(errors).toEqual([]);
  await admin.close();
});

test("offline disables editing and reconnect recovers", async ({ browser }) => {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const p = await context.newPage();
  await login(p, 1);
  await context.setOffline(true);
  await expect(p.getByText("Đang kết nối lại", { exact: true })).toBeVisible({
    timeout: 60000,
  });
  await expect(
    p.getByRole("button", { name: "Thêm", exact: true }).first(),
  ).toBeDisabled();
  await context.setOffline(false);
  await expect(p.getByText("Đang đồng bộ", { exact: true })).toBeVisible({
    timeout: 45000,
  });
  await expect(
    p.getByRole("button", { name: "Thêm", exact: true }).first(),
  ).toBeEnabled();
  await context.close();
});

test("request quote acceptance and conversion through both interfaces", async ({
  browser,
}) => {
  const c = await browser.newContext({ ignoreHTTPSErrors: true }),
    a = await browser.newContext({ ignoreHTTPSErrors: true });
  const customer = await c.newPage(),
    admin = await a.newPage();
  await login(customer, 1);
  await login(admin, 0);
  const name = "Cam theo yêu cầu UI " + Date.now();
  await customer
    .getByRole("button", { name: "Yêu cầu hàng", exact: true })
    .click();
  await customer
    .getByRole("button", { name: "Gửi yêu cầu", exact: true })
    .click();
  const create = customer.getByRole("dialog");
  await create.getByLabel("Tên mặt hàng").fill(name);
  await create.getByLabel("Số lượng", { exact: true }).fill("1");
  await create.getByLabel("Đơn vị mong muốn").fill("kg");
  await create
    .getByRole("button", { name: "Gửi yêu cầu", exact: true })
    .click();
  await expect(create).toHaveCount(0);
  await admin
    .getByRole("button", { name: "Yêu cầu hàng", exact: true })
    .click();
  await admin
    .locator("tbody tr")
    .filter({ hasText: name })
    .getByRole("button", { name: "Chi tiết" })
    .click();
  const dialog = admin.getByRole("dialog");
  await dialog.getByRole("button", { name: "Tiếp nhận", exact: true }).click();
  await dialog
    .getByRole("button", { name: "Soạn báo giá", exact: true })
    .click();
  await dialog
    .getByLabel("Đợt hàng đáp ứng")
    .selectOption(data.products[0].offerId);
  await dialog.getByLabel("Đơn giá thỏa thuận (đ)").fill("28000");
  const policies = await (
    await a.request.get("https://localhost:3443/api/v1/admin/config/policies")
  ).json();
  const policy = policies.find(
    (p: any) => p.group_id === data.groups.STUDENT && p.method === "COLLECTIVE",
  );
  await dialog.getByLabel("Chính sách giao").selectOption(policy.id);
  await dialog
    .getByRole("button", { name: "Gửi báo giá", exact: true })
    .click();
  const row = customer.locator("tbody tr").filter({ hasText: name });
  await expect(row.getByText("Đã báo giá", { exact: true })).toBeVisible();
  await row.getByRole("button", { name: "Chi tiết" }).click();
  const quote = customer.getByRole("dialog");
  await quote
    .getByRole("button", { name: "Chấp thuận báo giá mới nhất" })
    .click();
  await expect(
    quote.getByRole("button", { name: "Tạo đơn chờ duyệt từ báo giá" }),
  ).toBeEnabled();
  await quote
    .getByRole("button", { name: "Tạo đơn chờ duyệt từ báo giá" })
    .click();
  await expect(quote.getByText(/Đã tạo đơn #/)).toBeVisible();
  await customer.screenshot({
    path: path.join(evidence, "quote-flow.png"),
    fullPage: true,
  });
  await c.close();
  await a.close();
});

test("price and delivery changes require explicit confirmation", async ({
  browser,
}) => {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  await login(page, 1);
  const h = await browser.newContext({ ignoreHTTPSErrors: true });
  const admin = await h.newPage();
  await login(admin, 0);
  const session = await (
    await h.request.get("https://localhost:3443/api/v1/auth/session")
  ).json();
  const headers = {
    Origin: "https://localhost:3443",
    "X-CSRF-Token": session.csrfToken,
  };
  const offerId = data.products[2].offerId;
  const row = page.locator(`tr[data-offer-id="${offerId}"]`);
  await row.getByRole("button", { name: "Thêm", exact: true }).click();
  const offers = await (
    await h.request.get("https://localhost:3443/api/v1/admin/offers")
  ).json();
  const offer = offers.find((o: any) => o.id === offerId);
  const price = offer.prices.find(
    (p: any) => p.group_id === data.groups.STUDENT,
  );
  let catalogReads = 0;
  page.on("request", (r) => {
    if (r.url().endsWith("/api/v1/catalog/offers")) catalogReads++;
  });
  const change = await h.request.patch(
    "https://localhost:3443/api/v1/admin/offers/" + offerId,
    {
      headers,
      data: {
        expectedVersion: String(offer.version),
        prices: [
          {
            groupId: price.group_id,
            unitPrice: String(Number(price.unit_price) + 1000),
            expectedVersion: String(price.version),
          },
        ],
      },
    },
  );
  expect(change.ok()).toBe(true);
  await expect(
    page.getByText("Giá hoặc đợt bán đã thay đổi.", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Gửi đơn chờ duyệt" }),
  ).toBeDisabled();
  expect(catalogReads).toBe(0);
  await page.getByRole("button", { name: "Cập nhật và xem lại tổng" }).click();
  await expect(
    page.getByRole("button", { name: "Gửi đơn chờ duyệt" }),
  ).toBeEnabled();
  const policies = await (
    await h.request.get("https://localhost:3443/api/v1/admin/config/policies")
  ).json();
  const policy = policies.find(
    (p: any) => p.group_id === data.groups.STUDENT && p.method === "INDIVIDUAL",
  );
  await page.getByLabel("Cách giao", { exact: true }).selectOption(policy.id);
  const changed = await h.request.patch(
    "https://localhost:3443/api/v1/admin/config/policies/" + policy.id,
    {
      headers,
      data: {
        expectedVersion: String(policy.version),
        shippingFee: String(Number(policy.shipping_fee) + 1000),
      },
    },
  );
  expect(changed.ok()).toBe(true);
  await expect(
    page.getByText("Phí hoặc điều kiện giao đã thay đổi.", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Gửi đơn chờ duyệt" }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Cập nhật phí và xem lại tổng" })
    .click();
  await expect(
    page.getByRole("button", { name: "Gửi đơn chờ duyệt" }),
  ).toBeEnabled();
  // Restore the original sample prices/policy with fresh versions.
  const fresh = await (
    await h.request.get("https://localhost:3443/api/v1/admin/offers")
  ).json();
  const o = fresh.find((x: any) => x.id === offerId),
    p = o.prices.find((x: any) => x.group_id === price.group_id);
  expect(
    (
      await h.request.patch(
        "https://localhost:3443/api/v1/admin/offers/" + offerId,
        {
          headers,
          data: {
            expectedVersion: String(o.version),
            prices: [
              {
                groupId: p.group_id,
                unitPrice: price.unit_price,
                expectedVersion: String(p.version),
              },
            ],
          },
        },
      )
    ).ok(),
  ).toBe(true);
  expect(
    (
      await h.request.patch(
        "https://localhost:3443/api/v1/admin/config/policies/" + policy.id,
        {
          headers,
          data: {
            expectedVersion: String((await changed.json()).version),
            shippingFee: policy.shipping_fee,
          },
        },
      )
    ).ok(),
  ).toBe(true);
  await context.close();
  await h.close();
});
