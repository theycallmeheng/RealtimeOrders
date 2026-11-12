import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

const fixture = process.env.FOOD_MART_FIXTURE;
const accounts = fixture ? JSON.parse(readFileSync(fixture, "utf8")) : null;
test.skip(!fixture, "Requires the isolated Food Mart test app and demo fixture.");

for (const width of [360,390,768,1440]) {
  test(`catalog and pickup checkout fit ${width}px`, async ({page, baseURL}) => {
    await page.setViewportSize({width,height:850});
    const buyer = accounts.accounts[1];
    const session = await page.request.post("/api/v1/auth/login",{
      headers:{Origin:baseURL!},data:{identifier:buyer.phone,password:buyer.password},
    });
    expect(session.ok()).toBeTruthy();
    await page.goto("/menu");
    await expect(page.getByRole("heading",{name:"Menu hôm nay"})).toBeVisible();
    const search = page.getByLabel("Tìm món");
    await search.fill("Kho thử");
    const card = page.locator(".daily-product").filter({hasText:"Kho thử"}).first();
    await expect(card).toBeVisible();
    await expect(card.locator("del")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    if (width<=760) await expect(page.getByRole("navigation",{name:"Điều hướng mua hàng"})).toBeVisible();
    await card.getByRole("button",{name:"Thêm vào giỏ"}).click();
    await page.goto("/cart");
    const deliveryMethod = page.getByLabel("Cách nhận hàng");
    await expect(deliveryMethod).toBeVisible();
    if (await deliveryMethod.locator('option[value="COLLECTIVE"]').count()) {
      await deliveryMethod.selectOption("COLLECTIVE");
      await expect(page.getByLabel("Điểm nhận tập trung")).toBeVisible();
      await expect(page.getByText(/Nhận từ 17:00–18:00 ngày/)).toBeVisible();
    }
    await expect(page.getByText("Tổng thanh toán",{exact:true})).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}

test("seller stock workbench and admin VAT settings", async ({page,baseURL}) => {
  await page.setViewportSize({width:390,height:850});
  const seller = accounts.staffAccounts[0];
  expect((await page.request.post("/api/v1/auth/login",{headers:{Origin:baseURL!},
    data:{identifier:seller.phone,password:seller.password}})).ok()).toBeTruthy();
  await page.goto("/shop/stock");
  await expect(page.getByRole("heading",{name:"Kho và nhà cung cấp"})).toBeVisible();
  await page.getByRole("button",{name:"Nhập kho",exact:true}).click();
  await page.getByLabel("Loại phiếu").selectOption("OPENING");
  await expect(page.getByRole("button",{name:"Xác nhận nhập kho"})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.context().clearCookies();
  const admin = accounts.accounts[0];
  expect((await page.request.post("/api/v1/auth/login",{headers:{Origin:baseURL!},
    data:{identifier:admin.phone,password:admin.password}})).ok()).toBeTruthy();
  await page.goto("/admin/settings");
  await page.getByText("Thuế VAT",{exact:true}).click();
  await expect(page.getByLabel("Thuế suất mặc định (%)")).toBeVisible();
});
